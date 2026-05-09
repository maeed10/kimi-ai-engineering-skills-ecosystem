# Semgrep Rules Reference

Curated Semgrep rulesets and key rules for common vulnerability classes.
Use this reference when configuring `scripts/run-sast.py` or running Semgrep manually.

## Rulesets

| Ruleset | Semgrep flag | Coverage |
|---------|--------------|----------|
| OWASP Top 10 | `p/owasp-top-ten` | Injection, broken auth, sensitive data exposure, XXE, broken access control, security misconfiguration, XSS, insecure deserialization, known vulnerabilities, insufficient logging |
| CWE Top 25 | `p/cwe-top-25` | Most dangerous software weaknesses ranked by CWE |
| Secrets | `p/secrets` | Hardcoded API keys, tokens, passwords, private keys |
| Python Security | `python` | Python-specific injection, deserialization, path traversal |
| JavaScript Security | `javascript` | XSS, eval, prototype pollution, path traversal |
| TypeScript Security | `typescript` | Same as JS plus TS-specific unsafe patterns |
| CI Security | `p/ci` | Dangerous CI/CD configurations, poisoned pipeline execution |
| Command Injection | `p/command-injection` | OS command injection across languages |

## Key individual rules to enable

### Injection
- `sql-injection` — SQLi via string concatenation or unsafe interpolation.
- `command-injection` — OS command execution with user input.
- `ldap-injection` — Unsafe LDAP query construction.
- `xpath-injection` — XPath query interpolation.

### Authentication / Authorization
- `hardcoded-password` — Credentials embedded in source.
- `hardcoded-secrets` — API keys, tokens, private keys.
- `insecure-random` — Predictable randomness used for security.
- `weak-crypto` — Deprecated algorithms (MD5, SHA1, DES, ECB).

### Data handling
- `path-traversal` — File path built from user input without sanitization.
- `ssrf` — Server-Side Request Forgery via URL construction.
- `open-redirect` — Redirect target controlled by user input.
- `xxe` — XML External Entity processing enabled.

### Deserialization
- `deserialization` — Unsafe pickle, yaml.load, ObjectInputStream, etc.
- `unsafe-reflection` — Dynamic class loading from user input.

### Web / Client-side
- `xss` — Reflected/stored XSS via unescaped output.
- `eval` — Use of eval / exec / Function constructor.
- `prototype-pollution` — Merging user input into prototype chain.

## Running rules manually

```bash
# OWASP Top 10 on a directory
semgrep --config p/owasp-top-ten ./src

# Multiple rulesets combined
semgrep --config p/owasp-top-ten --config p/secrets ./src

# JSON output for downstream processing
semgrep --config p/owasp-top-ten ./src --json -o semgrep.json

# Specific rule on a single file
semgrep --config p/sql-injection ./app.py
```

## Severity mapping

Semgrep severity strings map to the skill's 5-level scale:

| Semgrep | Skill severity |
|---------|----------------|
| `error` | `critical` |
| `warning` | `high` |
| `info` | `medium` |
| (missing) | `medium` |

## Adding custom rules

Place `.yaml` or `.yml` Semgrep rule files in a `semgrep-rules/` directory and reference them:

```bash
semgrep --config semgrep-rules/ ./src
```

## False-positive handling

- NEVER suppress a finding because "it's just test code" or "temporary".
- If a finding is a confirmed false positive, document it in `security-false-positives.md` with:
  - Rule ID
  - File and line
  - Justification
  - Date and reviewer
- NEVER auto-suppress critical/high findings without human review.
