---
name: secret-manager
description: L0 sealed secret injection skill that ensures credentials enter sandboxes via file descriptors or tmpfs mounts without ever appearing in LLM context or tool outputs. Use whenever skills require API keys, tokens, or passwords. Includes gateway output scrubbing, entropy-based leak detection, and short-lived credential rotation.
---

# secret-manager

## Core Principle

Secrets must never transit through the LLM context window or appear in tool output.
All secret material is injected into sandboxes at runtime through channels the LLM cannot observe (file descriptors, tmpfs mounts) and is scrubbed from all gateway output before the LLM receives it.

## Injection Channels

| Channel | Mechanism | Visibility to LLM |
|---------|-----------|-------------------|
| File Descriptor | `exec` with `fd >` redirection | None |
| tmpfs Mount | `/run/secrets/<name>` created by gateway | None |
| Environment Variable | **BLOCKED by policy** | Full |

**When injecting secrets:**
1. Prefer fd injection for single-use tokens (pass `--token /dev/fd/3` to child, write token to fd 3 in gateway).
2. Use tmpfs mount when multiple processes in the sandbox need the same secret (`mkdir /run/secrets && mount -t tmpfs -o size=1m tmpfs /run/secrets`).
3. **Never** pass secrets as literal strings in tool arguments or prompt text.

## Gateway Scrubbing Rules

Before any tool output reaches the LLM:
1. Run `scripts/scrub_output.py` against stdout and stderr.
2. Reject any output where Shannon entropy of a candidate string exceeds the threshold defined in `references/scrubber_rules.md`.
3. Reject any output matching known secret regex patterns (API keys, tokens, private keys).
4. On detection: redact with `[REDACTED:<type>]` and emit a `secret_leak` audit event.

## Policy Engine Rules

Enforce these as hard constraints in the policy engine:
- `DENY` any tool `arguments` field containing a string that matches secret regex patterns or exceeds entropy threshold.
- `DENY` any tool `arguments` field referencing `/run/secrets/` path (the path itself is allowed; the secret content is not).
- `DENY` environment variable injection for keys matching `*TOKEN*`, `*KEY*`, `*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*` unless value is a `/run/secrets/` reference.
- `ALLOW` env var value `/run/secrets/github_token` (the path string) but `DENY` its resolved content.

## Short-Lived Credential Rotation

1. All dynamically issued credentials have a TTL ≤ 1 hour.
2. Gateway requests credentials from HashiCorp Vault or host-side secure store using an approved mTLS client certificate.
3. On sandbox termination, gateway revokes the lease (Vault) or zeroes the tmpfs mount.
4. For static long-lived secrets (emergency only): store in host-side encrypted file, inject via fd on each sandbox start, never cache in gateway memory beyond the request lifecycle.

## Workflow: Injecting a Secret into a Sandbox

```
1. Determine secret name (e.g., GITHUB_TOKEN)
2. Check if secret exists in host-side store or Vault
3. Gateway opens fd 3, writes secret value
4. Gateway mounts tmpfs at /run/secrets/ (if multi-process needed)
5. Gateway execs sandbox with:
   - env: GITHUB_TOKEN_FILE=/run/secrets/github_token  (safe: contains only path)
   - fd 3 mapped to /dev/fd/3 inside sandbox
   - OR tmpfs file /run/secrets/github_token
6. Sandbox reads secret from fd or tmpfs
7. Gateway runs scrub_output.py on all tool stdout/stderr
8. Policy engine blocks any tool arg containing secret pattern
9. On exit: gateway wipes tmpfs / revokes Vault lease
```

## Integration Points

- **tool-execution-gateway**: Load `scripts/scrub_output.py` as post-processor on every tool call.
- **policy-engine**: Load `references/scrubber_rules.md` to compile deny-list regexes.
- **sandbox runtime**: Load `references/secret_injection_patterns.md` to configure fd/tmpfs mounts.
- **Vault / host store**: Use `VAULT_ADDR` and `VAULT_CACERT` env vars (gateway-side only, never exposed to LLM).

## Audit and Incident Response

- Every secret injection event logs: timestamp, secret name (not value), sandbox ID, injection channel.
- Every scrub hit logs: timestamp, secret type (not value), output channel (stdout/stderr/tool arg), redaction count.
- On leak detection: immediately terminate sandbox, revoke credential, alert operator.
