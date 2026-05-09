# CWE Mapping Reference

Mapping from common tool rule IDs to CWE identifiers. Expand as the rule surface grows.

## Semgrep → CWE

| Semgrep check_id / rule keyword | CWE |
|---------------------------------|-----|
| `sql-injection` | CWE-89 |
| `command-injection` | CWE-78 |
| `path-traversal` | CWE-22 |
| `ssrf` | CWE-918 |
| `xss` | CWE-79 |
| `eval` | CWE-95 |
| `deserialization` | CWE-502 |
| `open-redirect` | CWE-601 |
| `ldap-injection` | CWE-90 |
| `xpath-injection` | CWE-91 |
| `xxe` | CWE-611 |
| `hardcoded-secrets` | CWE-798 |
| `hardcoded-password` | CWE-798 |
| `insecure-hash-algorithm` | CWE-328 |
| `weak-crypto` | CWE-327 |
| `insecure-random` | CWE-338 |
| `prototype-pollution` | CWE-1321 |
| `unsafe-reflection` | CWE-470 |
| `ci` (poisoned pipeline) | CWE-1127 |

## Bandit → CWE

| Bandit test_id | CWE |
|----------------|-----|
| `B102` (exec) | CWE-78 |
| `B105` / `B106` / `B107` (hardcoded passwords) | CWE-798 |
| `B201` (flask debug) | CWE-489 |
| `B301` (pickle) | CWE-502 |
| `B307` (eval) | CWE-95 |
| `B308` (mark_safe) | CWE-79 |
| `B601` (paramiko no host key verify) | CWE-295 |
| `B602` (subprocess with shell) | CWE-78 |
| `B603` (subprocess without shell) | CWE-78 |
| `B605` (start process with shell) | CWE-78 |
| `B607` (start process with partial path) | CWE-426 |
| `B608` (SQL injection) | CWE-89 |
| `B609` (wildcard injection) | CWE-78 |

## ESLint security → CWE

| ESLint rule | CWE |
|-------------|-----|
| `detect-eval-with-expression` | CWE-95 |
| `detect-non-literal-fs-filename` | CWE-22 |
| `detect-non-literal-regexp` | CWE-400 |
| `detect-non-literal-require` | CWE-96 |
| `detect-object-injection` | CWE-915 |
| `detect-possible-timing-attacks` | CWE-208 |
| `detect-pseudoRandomBytes` | CWE-338 |
| `detect-unsafe-regex` | CWE-185 |

## STRIDE → CWE (indicative)

| STRIDE category | Representative CWEs |
|-----------------|---------------------|
| Spoofing | CWE-290, CWE-295, CWE-798 |
| Tampering | CWE-471, CWE-354 |
| Repudiation | CWE-778 |
| Information Disclosure | CWE-200, CWE-532, CWE-640 |
| Denial of Service | CWE-400, CWE-770, CWE-799 |
| Elevation of Privilege | CWE-269, CWE-250, CWE-862 |

## Notes
- When a tool does not report a CWE directly, use this mapping or attempt regex extraction (`CWE-\d+`).
- If no mapping exists, record `CWE-UNKNOWN` and update this file.
- NEVER leave a critical/high finding without at least an attempted CWE assignment.
