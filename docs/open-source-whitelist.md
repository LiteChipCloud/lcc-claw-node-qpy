# Open Source Whitelist (v1.0)

Only the following file classes are allowed in OSS release package.

## 1. Allowed

1. Runtime source under `usr_mirror/`
2. Example config under `examples/`
3. Docs under `docs/`
4. Test scaffolds under `tests/mock_gateway/`
5. Hygiene tools under `tools/`
6. Repo governance files (`README`, `LICENSE`, `NOTICE`, `SECURITY`, `CONTRIBUTING`, templates)

## 2. Forbidden

1. Real tokens/keys/passwords/certs
2. Internal hostnames, private IP ranges, internal domains
3. Customer identifiers and production tenant mappings
4. Internal operational playbooks with private infra references
5. Raw production logs

## 3. Release Checklist

1. `sanitize_check.py` passes.
2. Manual second review for secrets and private topology.
3. License and attribution review completed.
