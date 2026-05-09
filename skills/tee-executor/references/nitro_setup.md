# AWS Nitro Enclaves Setup Guide

Complete guide for enabling, configuring, and running enclaves for the tee-executor backend.

## Table of Contents
1. [Instance Requirements](#instance-requirements)
2. [Enabling Nitro Enclaves](#enabling-nitro-enclaves)
3. [Installing nitro-cli](#installing-nitro-cli)
4. [EIF Build Process](#eif-build-process)
5. [vsock Configuration](#vsock-configuration)
6. [Running Enclaves](#running-enclaves)
7. [Debugging](#debugging)

## Instance Requirements

| Requirement | Specification |
|-------------|--------------|
| Instance family | `m5`, `m5d`, `m5n`, `m5dn`, `m6i`, `c5`, `c5d`, `c5n`, `c6i`, `r5`, `r5d`, `r5n`, `r5dn`, `r6i` |
| Minimum size | `xlarge` (2 vCPUs for enclave + 2 for host) |
| Hypervisor | Nitro |
| Enclave-enabled | Must be enabled at instance launch |

Enable enclave support at launch:
```bash
aws ec2 run-instances \
  --image-id ami-xxxxxxxx \
  --instance-type m5.xlarge \
  --enclave-options Enabled=true \
  ...
```

Or modify a stopped instance:
```bash
aws ec2 modify-instance-attribute \
  --instance-id i-xxxxxxxx \
  --enclave-options Enabled=true
```

## Enabling Nitro Enclaves

### 1. Configure the Enclave Allocator

Edit `/etc/nitro_enclaves/allocator.yaml`:
```yaml
---
memory_mib: 512
cpu_count: 2
# Optional: CPU pool specification
# cpu_pool: 0,1
```

Memory constraints:
- Minimum: 64 MiB
- Must be a power of 2 for pages: 64, 128, 256, 512, 1024, 2048, 4096, ...
- Host memory is reserved; ensure instance has enough total RAM

Restart allocator:
```bash
sudo systemctl restart nitro-enclaves-allocator.service
```

### 2. Configure vsock Device

The vsock device is automatically created by the Nitro driver. Verify:
```bash
ls -la /dev/vsock
# crw-rw-rw- 1 root root 10, 121 Jun  1 00:00 /dev/vsock
```

Check CID assignment:
```bash
cat /sys/devices/virtual/misc/vsock/cid
# Host CID: typically 3 (VMADDR_CID_HOST)
# Enclave CID: dynamically assigned, query via nitro-cli describe-enclaves
```

## Installing nitro-cli

### Amazon Linux 2023 / Amazon Linux 2

```bash
sudo yum update -y
sudo amazon-linux-extras install aws-nitro-enclaves-cli -y
sudo yum install aws-nitro-enclaves-cli-devel -y
sudo usermod -aG ne ec2-user
```

### Ubuntu 22.04

```bash
sudo apt update
# Download from AWS releases
wget https://aws-nitro-enclaves-cli.s3.amazonaws.com/ubuntu-22.04/aarch64/nitro-cli_1.3.0-0-0_amd64.deb
sudo dpkg -i nitro-cli_*.deb
sudo apt-get install -f
```

Verify installation:
```bash
nitro-cli --version
nitro-cli build-enclave --help
nitro-cli run-enclave --help
```

## EIF Build Process

### Dockerfile Requirements

The Dockerfile must produce a minimal, stripped-down OS:

```dockerfile
# Minimal EIF base for agent execution
FROM alpine:3.19 AS builder

# Install only runtime dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    ca-certificates

# Copy agent code
WORKDIR /app
COPY agent_runtime/ ./
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Final stage: absolutely minimal
FROM scratch
# Or use alpine with minimal packages:
# FROM alpine:3.19
# RUN apk add --no-cache python3 ca-certificates

WORKDIR /app
COPY --from=builder /app/ ./
COPY --from=builder /usr/bin/python3 /usr/bin/python3
COPY --from=builder /lib/ /lib/
COPY --from=builder /usr/lib/ /usr/lib/

# NO shell, NO ssh, NO network tools
# ENTRYPOINT is the only executable path
ENTRYPOINT ["/usr/bin/python3", "-m", "agent_runtime.enclave_main"]
```

### Build Command

```bash
nitro-cli build-enclave \
  --docker-uri my-agent-runtime:latest \
  --output-file agent.eif
```

### Build Output

```json
{
  "Measurements": {
    "HashAlgorithm": "Sha384 { ... }",
    "PCR0": "abc123...",
    "PCR1": "def456...",
    "PCR2": "ghi789..."
  },
  "EnclaveName": "agent.eif"
}
```

**PCR meanings:**
| PCR | Content | Stability |
|-----|---------|-----------|
| PCR0 | EIF image hash (kernel + initrd + cmdline) | Reproducible per build |
| PCR1 | Linux kernel hash | Stable for same kernel version |
| PCR2 | Application hash | Changes with code changes |

### Reproducible Builds

To ensure PCR0 is reproducible:
1. Pin all base image digests (`FROM alpine:3.19@sha256:...`)
2. Pin all package versions
3. Use multi-stage builds to exclude build tools from final image
4. Sort all file copies deterministically
5. Record the PCR0 after build; add to `TEE_PCR0_WHITELIST`

## vsock Configuration

### vsock Proxy Architecture

```
+------------------------------------------+
|  Host (CID 0x3)                          |
|  +------------------+  HTTP/TLS         |
|  | vsock proxy      | <------------->   |
|  | :8000 (vsock)    |   external APIs   |
|  | :8080 (TCP)      |                   |
|  +------------------+                   |
+------------------------------------------+
                    | vsock (AF_VSOCK)
                    |
+------------------------------------------+
|  Enclave (CID auto-assigned)             |
|  +------------------+                    |
|  | agent runtime    |                    |
|  | connects to      |                    |
|  | CID 3, port 8000 |                    |
|  +------------------+                    |
+------------------------------------------+
```

### Starting the vsock Proxy

```bash
# Option 1: Python vsock proxy (see scripts/vsock_proxy.py)
python3 vsock_proxy.py \
  --vsock-port 8000 \
  --upstream-url https://api.tools.internal \
  --cert /etc/ssl/certs/proxy.crt \
  --key /etc/ssl/private/proxy.key

# Option 2: Simple socat relay (development only)
socat \
  VSOCK-LISTEN:8000,fork \
  TCP:api.tools.internal:443
```

### Enclave vsock Client

Inside the enclave, connect to the host proxy:
```python
import socket

# AF_VSOCK socket
sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
# CID 3 = host, port 8000 = proxy
sock.connect((3, 8000))

# Send HTTP request over vsock
sock.send(b"GET /tools/llm HTTP/1.1\r\nHost: proxy\r\n\r\n")
response = sock.recv(65536)
```

## Running Enclaves

### Basic Run

```bash
nitro-cli run-enclave \
  --eif-path agent.eif \
  --cpu-count 2 \
  --memory 512 \
  --enclave-cid 16 \
  --debug-mode
```

### Production Run (no debug)

```bash
nitro-cli run-enclave \
  --eif-path agent.eif \
  --cpu-count 2 \
  --memory 512 \
  --enclave-cid 16
```

**Never use `--debug-mode` in production** — it enables console output that leaks enclave state.

### Query Running Enclaves

```bash
nitro-cli describe-enclaves
```

Output:
```json
[
  {
    "EnclaveID": "i-0abcd1234-enc0123456789abcdef0",
    "ProcessID": 1234,
    "EnclaveCID": 16,
    "NumberOfCPUs": 2,
    "CPUIDs": [1, 3],
    "MemoryMiB": 512,
    "State": "RUNNING",
    "Flags": "DEBUG_MODE"
  }
]
```

### Terminate

```bash
nitro-cli terminate-enclave --enclave-id i-0abcd1234-enc0123456789abcdef0
```

## Debugging

### Enclave Console (debug mode only)

```bash
nitro-cli console --enclave-id i-0abcd1234-enc0123456789abcdef0
```

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `Insufficient memory` | Allocator not configured | Edit `allocator.yaml`, restart service |
| `Insufficient CPUs` | Allocator CPU count too low | Increase `cpu_count` in allocator |
| `Build failure` | Docker context too large | Use `.dockerignore`, multi-stage build |
| `vsock connection refused` | Proxy not running | Start `vsock_proxy.py` before enclave |
| `Attestation fails` | Clock skew or bad PCR | Check `date`, verify PCR0 whitelist |
| `Enclave won't start` | Debug mode on non-debug AMI | Use Nitro Enclaves-enabled AMI |

### Log Locations

| Component | Log Path |
|-----------|----------|
| Allocator | `/var/log/nitro_enclaves/allocator.log` |
| nitro-cli | stdout/stderr (run with `--debug-verbose` for more) |
| vsock proxy | Configurable, default `/var/log/tee-executor/vsock-proxy.log` |
| Enclave console | `nitro-cli console` (debug mode only) |
