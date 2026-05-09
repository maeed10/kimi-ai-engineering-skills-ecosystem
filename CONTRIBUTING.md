# Contributing to the Kimi AI Engineering Skills Ecosystem

Thank you for your interest in contributing. This document outlines the standards and processes for participating in this project.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Run the validation suite to ensure your environment is correct:
   ```bash
   python tests/validate_config.py
   pytest tests/ -v
   ```

## Adding a New Skill

Skills follow a standardized directory structure:

```
skills/<skill-name>/
├── SKILL.md              # Required: Full documentation
├── scripts/              # Optional: Automation scripts
├── references/           # Optional: Supporting documents
└── fixtures/             # Optional: Test data
```

### SKILL.md Requirements

Every skill must include:

- **Trigger conditions** — When should this skill activate?
- **Dependencies** — What other skills or tools does it require?
- **Inputs and outputs** — Clear interface definition
- **Safety boundaries** — What this skill will NOT do
- **Usage examples** — Concrete examples of invocation

### Skill Naming

- Use lowercase with hyphens: `code-tester`, `architecture-design`
- Be descriptive: prefer `api-contract-tester` over `api-tester`
- Avoid vendor-specific names unless the skill is genuinely vendor-locked

## Modifying Policies

The policy files in `policy/` are the contract between the ecosystem and its users. Changes require:

1. **Rule ID preservation** — Never reuse a deleted rule ID
2. **Backward compatibility** — New rules default to `severity: LOW` unless justified
3. **Validation** — `validate_config.py` must pass after any change
4. **Documentation** — Update `docs/ECOSYSTEM-OPERATIONS.md` if the change affects operations

## Code Standards

- Python: PEP 8 compliant
- Shell scripts: `shellcheck` clean
- YAML: Validated with `yamllint`
- JSON: Validated with `jsonlint`

## Testing

All contributions must include appropriate tests:

- **New skills**: Add a validation check in `validate_config.py` if the skill declares capabilities
- **New policies**: The policy must be referenced in `manifest.json` and pass integrity checks
- **Bug fixes**: Include a regression test

## Security

If you discover a security issue:

1. **Do NOT open a public issue**
2. Email the maintainers directly with a detailed report
3. Allow reasonable time for remediation before public disclosure

## Code of Conduct

- Be respectful and constructive
- Focus on the technical merits of contributions
- Assume good intent
- Help others learn

## Questions?

Open a discussion issue for questions that don't fit into bug reports or feature requests.
