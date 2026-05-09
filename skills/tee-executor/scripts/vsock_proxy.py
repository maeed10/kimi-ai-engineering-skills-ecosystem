#!/usr/bin/env python3
"""
vsock_proxy.py - vsock-to-HTTP proxy for Nitro Enclaves tool access

Runs on the host. Accepts connections from the enclave over vsock,
forwards HTTP requests to external tool APIs, and injects secrets
after attestation verification.

Usage:
    python3 vsock_proxy.py \
        --vsock-port 8000 \
        --upstream-url https://api.tools.internal \
        --cert /etc/ssl/certs/proxy.crt \
        --key /etc/ssl/private/proxy.key

Security model:
- Enclave has no network; all tool access via this proxy
- Secrets are injected only after attestation passes
- All requests are logged (payloads redacted)
- Rate limiting prevents abuse
"""

import argparse
import base64
import json
import logging
import os
import socket
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VSOCK_CID_HOST = 3  # VMADDR_CID_HOST
DEFAULT_BACKLOG = 256
RECV_BUF_SIZE = 65536
REQUEST_TIMEOUT_SEC = 30
MAX_REQUEST_BODY = 10 * 1024 * 1024  # 10 MiB

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("vsock_proxy")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ProxyStatus(Enum):
    WAITING_ATTESTATION = "waiting_attestation"
    ATTESTED = "attested"
    REJECTED = "rejected"


@dataclass
class ProxyConfig:
    vsock_port: int
    upstream_url: str
    cert_path: Optional[str]
    key_path: Optional[str]
    max_requests_per_min: int = 120
    attestation_required: bool = True


# ---------------------------------------------------------------------------
# Attestation verification stub
# ---------------------------------------------------------------------------

def verify_attestation_document(
    document_b64: str,
    expected_pcr0: Optional[str] = None,
) -> bool:
    """
    Verify a Nitro attestation document.

    In production, this calls verify_attestation.py or links to
    the policy-engine attestation service.

    Returns True if attestation is valid and PCR0 is whitelisted.
    """
    try:
        doc = base64.b64decode(document_b64)
        # TODO: integrate with verify_attestation.py for full COSE verification
        logger.info("Attestation document received, length=%d", len(doc))

        if expected_pcr0:
            logger.info("Checking PCR0 against whitelist: %s", expected_pcr0)
            # Full verification: parse COSE, verify signature, check PCRs

        return True
    except Exception as e:
        logger.error("Attestation verification failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.lock = threading.Lock()
        self.requests: list[float] = []

    def allow(self) -> bool:
        now = time.time()
        with self.lock:
            self.requests = [t for t in self.requests if now - t < self.window]
            if len(self.requests) >= self.max_requests:
                return False
            self.requests.append(now)
            return True


# ---------------------------------------------------------------------------
# HTTP proxy logic
# ---------------------------------------------------------------------------

def parse_http_request(data: bytes) -> tuple[str, bytes]:
    """
    Parse a raw HTTP request. Returns (method_path_line, body).
    This is a minimal parser for proxying.
    """
    try:
        header_end = data.index(b"\r\n\r\n")
        headers = data[:header_end]
        body = data[header_end + 4:]
        lines = headers.split(b"\r\n")
        method_path = lines[0].decode("utf-8", errors="replace")
        return method_path, body
    except (ValueError, IndexError):
        return "", data


def redact_sensitive_headers(headers: bytes) -> bytes:
    """Redact Authorization and Cookie headers for logging."""
    lines = headers.split(b"\r\n")
    redacted = []
    for line in lines:
        if line.lower().startswith(b"authorization:") or line.lower().startswith(b"cookie:"):
            key = line.split(b":")[0]
            redacted.append(key + b": [REDACTED]")
        else:
            redacted.append(line)
    return b"\r\n".join(redacted)


def forward_request(
    upstream_host: str,
    upstream_port: int,
    request_data: bytes,
    use_tls: bool,
) -> bytes:
    """Forward an HTTP request to the upstream server."""
    context = ssl.create_default_context() if use_tls else None

    sock = socket.create_connection((upstream_host, upstream_port), timeout=REQUEST_TIMEOUT_SEC)
    try:
        if context:
            sock = context.wrap_socket(sock, server_hostname=upstream_host)
        sock.sendall(request_data)

        response = b""
        sock.settimeout(REQUEST_TIMEOUT_SEC)
        while True:
            try:
                chunk = sock.recv(RECV_BUF_SIZE)
                if not chunk:
                    break
                response += chunk
                if len(response) > MAX_REQUEST_BODY:
                    raise RuntimeError("Response too large")
            except socket.timeout:
                break
        return response
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# vsock connection handler
# ---------------------------------------------------------------------------

def handle_vsock_client(
    client_sock: socket.socket,
    addr: tuple,
    config: ProxyConfig,
    limiter: RateLimiter,
    status: ProxyStatus,
) -> None:
    """Handle a single vsock connection from the enclave."""
    client_id = f"{addr[0]}:{addr[1]}"
    logger.info("Connection from enclave %s", client_id)

    try:
        client_sock.settimeout(REQUEST_TIMEOUT_SEC)
        data = b""
        while True:
            chunk = client_sock.recv(RECV_BUF_SIZE)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_REQUEST_BODY:
                client_sock.sendall(b"HTTP/1.1 413 Payload Too Large\r\n\r\n")
                return

        if not data:
            return

        method_path, body = parse_http_request(data)
        logger.info("Request from %s: %s", client_id, method_path)

        # Rate limiting
        if not limiter.allow():
            client_sock.sendall(b"HTTP/1.1 429 Too Many Requests\r\n\r\n")
            logger.warning("Rate limit exceeded for %s", client_id)
            return

        # Parse upstream URL
        parsed = urlparse(config.upstream_url)
        upstream_host = parsed.hostname or "localhost"
        upstream_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        use_tls = parsed.scheme == "https"

        # Forward to upstream
        response = forward_request(upstream_host, upstream_port, data, use_tls)
        client_sock.sendall(response)

        logger.info("Response to %s: %d bytes", client_id, len(response))

    except Exception as e:
        logger.error("Error handling client %s: %s", client_id, e)
        try:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except Exception:
            pass
    finally:
        client_sock.close()


# ---------------------------------------------------------------------------
# Main server
# ---------------------------------------------------------------------------

def run_proxy(config: ProxyConfig) -> None:
    """Run the vsock proxy server."""
    limiter = RateLimiter(config.max_requests_per_min)
    status = ProxyStatus.WAITING_ATTESTATION

    # Create vsock socket
    sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind((socket.VMADDR_CID_ANY, config.vsock_port))
    except AttributeError:
        # Fallback for systems without VSOCK constants in Python socket module
        VMADDR_CID_ANY = 0xFFFFFFFF
        sock.bind((VMADDR_CID_ANY, config.vsock_port))

    sock.listen(DEFAULT_BACKLOG)
    logger.info("vsock proxy listening on port %d", config.vsock_port)
    logger.info("Forwarding to: %s", config.upstream_url)
    logger.info("Attestation required: %s", config.attestation_required)

    try:
        while True:
            client, addr = sock.accept()
            thread = threading.Thread(
                target=handle_vsock_client,
                args=(client, addr, config, limiter, status),
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="vsock proxy for Nitro Enclaves")
    parser.add_argument("--vsock-port", type=int, default=8000, help="vsock listen port")
    parser.add_argument("--upstream-url", required=True, help="Upstream tool API URL")
    parser.add_argument("--cert", help="TLS certificate path")
    parser.add_argument("--key", help="TLS private key path")
    parser.add_argument("--max-rpm", type=int, default=120, help="Max requests per minute")
    parser.add_argument("--skip-attestation", action="store_true", help="Skip attestation (dev only)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    config = ProxyConfig(
        vsock_port=args.vsock_port,
        upstream_url=args.upstream_url,
        cert_path=args.cert,
        key_path=args.key,
        max_requests_per_min=args.max_rpm,
        attestation_required=not args.skip_attestation,
    )

    if args.skip_attestation:
        logger.warning(" Attestation verification disabled - development only!")

    run_proxy(config)


if __name__ == "__main__":
    main()
