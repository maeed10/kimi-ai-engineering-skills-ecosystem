# Scrubber Rules

Reference for the gateway output scrubber. Loaded by the policy engine to compile deny-list regexes and by `scripts/scrub_output.py` to redact secrets from tool output.

## Secret Regex Patterns

Apply all patterns case-insensitively unless noted.

### GitHub Personal Access Tokens

```regex
gh[pousr]_[A-Za-z0-9_]{36,251}
```

- `ghp_` classic / fine-grained personal access token
- `gho_` OAuth access token
- `ghu_` GitHub user-to-server token
- `ghs_` GitHub server-to-server token
- `ghr_` refresh token

### AWS Access Keys

```regex
AKIA[0-9A-Z]{16}
```

```regex
ASIA[0-9A-Z]{16}
```

(STS temporary credentials)

### AWS Secret Access Key (high-entropy base64)

```regex
(?i)aws(.{0,20})?(?-i)[^0-9A-Za-z/+=]{0,1}[0-9A-Za-z/+=]{40}[^0-9A-Za-z/+=]{0,1}
```

Context-aware: require "aws" keyword within 20 characters before or after.

### E2B API Keys

```regex
[e2b][-_]?[a-zA-Z0-9]{32,64}
```

Context-aware: require "e2b" keyword within 10 characters.

### Generic API Keys

```regex
(?i)(api[_-]?key|apikey|api[_-]?secret)[\s]*[=:]+[\s]*["']?[a-zA-Z0-9_\-]{16,128}["']?
```

### Private Keys

```regex
-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----
```

### Bearer Tokens

```regex
(?i)bearer\s+[a-zA-Z0-9_\-\.=]{20,}
```

### URL with Embedded Credentials

```regex
[a-zA-Z][a-zA-Z0-9+\-.]*://[^:]+:[^@]+@[^/]+/
```

## Entropy Thresholds

Use Shannon entropy to catch hex/base64 tokens that evade regex patterns.

### Calculation

```python
import math
from collections import Counter

def shannon_entropy(s: str) -> float:
    counts = Counter(s)
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())
```

### Thresholds by Token Length

| Length Range | Minimum Entropy | Action |
|--------------|-----------------|--------|
| 32–48        | 4.5 bits/char   | Flag for review |
| 48–64        | 5.0 bits/char   | Redact + audit |
| 64+          | 5.5 bits/char   | Redact + audit + alert |

### Heuristic Filters (reduce false positives)

Skip candidate if it matches any of the following:
- All same character (`aaaa...`)
- Repeating 2-char pattern (`ababab...`)
- Common English word in dictionary (`password123` has low entropy anyway)
- UUID format (`xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`) — these are identifiers, not secrets, unless context says otherwise

## Redaction Format

When a secret is redacted, replace it with:

```
[REDACTED:<type>]
```

Examples:
- `[REDACTED:github_token]`
- `[REDACTED:aws_secret_key]`
- `[REDACTED:private_key]`
- `[REDACTED:high_entropy]` (entropy-only detection)

## Policy Engine Compiled Rules

```yaml
scrubber:
  regex_rules:
    - name: github_token
      pattern: "gh[pousr]_[A-Za-z0-9_]{36,251}"
    - name: aws_access_key
      pattern: "AKIA[0-9A-Z]{16}"
    - name: aws_secret_key
      pattern: "(?i:aws)(.{0,20})?[^0-9A-Za-z/+=]{0,1}[0-9A-Za-z/+=]{40}[^0-9A-Za-z/+=]{0,1}"
      context: true
    - name: e2b_api_key
      pattern: "[e2b][-_]?[a-zA-Z0-9]{32,64}"
      context: true
    - name: api_key_literal
      pattern: "(?i)(api[_-]?key|apikey|api[_-]?secret)[\\s]*[=:]+[\\s]*[\"']?[a-zA-Z0-9_\\-]{16,128}[\"']?"
    - name: private_key
      pattern: "-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
      multiline: true
    - name: bearer_token
      pattern: "(?i)bearer\\s+[a-zA-Z0-9_\\-\\.]{20,}"
    - name: url_with_creds
      pattern: "[a-zA-Z][a-zA-Z0-9+\\-.]*://[^:]+:[^@]+@[^/]+/"
  entropy_rules:
    - min_length: 32
      max_length: 48
      min_entropy: 4.5
      action: flag
    - min_length: 48
      max_length: 64
      min_entropy: 5.0
      action: redact
    - min_length: 64
      min_entropy: 5.5
      action: alert
```
