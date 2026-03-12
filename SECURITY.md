# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| v1.0.x | Yes |
| < v1.0.0 | No |

## Reporting a Vulnerability

1. Do not open public issue for active secret leakage or exploit chain.
2. Contact maintainers with:
- Repro steps
- Affected version/commit
- Impact and suggested mitigation
3. Maintainers will acknowledge within 3 business days.

## Secret Handling Baseline

1. Never commit real tokens/keys/passwords.
2. Never commit private IP/domain/tenant identifiers from production.
3. Run `python3 tools/sanitize_check.py --root .` before every release tag.
