# Secret Injection Patterns

Reference for configuring sandbox runtime and gateway to inject secrets without LLM exposure.

## File Descriptor Injection

Use when the child process accepts a file path or fd number for the secret.

### Gateway-side (Python pseudocode)

```python
import os, subprocess

secret_value = vault.read("github_token")  # never stored in LLM context

read_fd, write_fd = os.pipe()
os.write(write_fd, secret_value.encode())
os.close(write_fd)

proc = subprocess.Popen(
    ["sandbox", "--token-file", "/dev/fd/3"],
    pass_fds=(read_fd,),
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
# read_fd is now fd 3 in the child because pass_fds starts at 3
```

### Sandbox-side

```python
import os

token = os.read(3, 8192).decode()  # read from fd 3
os.close(3)
```

**Security property**: The secret value exists only in kernel pipe buffers and the child process address space. The LLM never sees the value because it is not present in any text exchanged with the LLM.

## tmpfs Mount Injection

Use when multiple processes in the sandbox need to read the same secret independently.

### Gateway-side

```python
import tempfile, os, subprocess

# Create tmpfs mount point in sandbox namespace
mount_point = "/run/secrets"
os.makedirs(mount_point, exist_ok=True)
os.system(f"mount -t tmpfs -o size=1m,mode=0700,uid={sandbox_uid} tmpfs {mount_point}")

# Write secret with restricted permissions
secret_path = f"{mount_point}/github_token"
with os.open(secret_path, os.O_WRONLY | os.O_CREAT, 0o600) as fd:
    os.write(fd, secret_value.encode())

# Pass only the path to the LLM-visible layer
env = {"GITHUB_TOKEN_FILE": secret_path}  # safe: contains only path string
```

### Sandbox-side

```python
token_file = os.environ["GITHUB_TOKEN_FILE"]
with open(token_file, "r") as f:
    token = f.read().strip()
```

**Cleanup requirement**: On sandbox termination, the gateway must:
1. Unmount the tmpfs: `umount -l /run/secrets`
2. Remove mount point: `rmdir /run/secrets`
3. Revoke Vault lease if applicable.

## Environment Variable Isolation

Environment variables are the highest-risk channel because they appear in `ps e`, `/proc/<pid>/environ`, and may be logged by tools.

### Allowed Patterns

| Pattern | Example | Risk Level |
|---------|---------|------------|
| Path reference to secret file | `GITHUB_TOKEN_FILE=/run/secrets/github_token` | Low (path only, no value) |
| Vault role reference | `VAULT_ROLE=github-actions` | Low (metadata only) |

### Blocked Patterns

| Pattern | Example | Block Reason |
|---------|---------|--------------|
| Literal token in env | `GITHUB_TOKEN=ghp_xxxxxxxx` | Direct exposure in process environment |
| Base64-encoded secret | `API_KEY_BASE64=Z2hwX...` | Trivially decoded, same exposure |
| Secret in command-line arg | `--token ghp_xxxxxxxx` | Visible in `ps` and shell history |

### Policy Implementation

```yaml
# policy-engine rule (YAML pseudocode)
rules:
  - id: deny_literal_secret_in_env
    match:
      - field: "tool.arguments.environment"
        pattern: "(?i)(token|key|secret|password|credential)"
    action: DENY
    reason: "Environment variables must not contain secret values. Use /run/secrets/ path references."
```

## Namespace Isolation

For defense in depth, create the sandbox in a separate Linux namespace so that `/run/secrets/` is not visible to host processes:

```python
import ctypes, os

CLONE_NEWNS = 0x00020000
CLONE_NEWPID = 0x20000000

# unshare mount and PID namespaces
libc = ctypes.CDLL("libc.so.6")
libc.unshare(CLONE_NEWNS | CLONE_NEWPID)

# remount /run/secrets so it is private to this namespace
os.system("mount --make-private /run/secrets")
```

## Checklist Before Enabling a New Secret Channel

- [ ] Secret value does not appear in any string the LLM receives
- [ ] Secret value does not appear in tool arguments
- [ ] Secret value does not appear in tool stdout or stderr (verified by scrubber)
- [ ] Sandbox has no read access to the host-side secret store
- [ ] tmpfs is unmounted and zeroed on sandbox exit
- [ ] File descriptors are CLOEXEC where possible
- [ ] Vault lease is revoked on sandbox exit
