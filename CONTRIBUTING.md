# Contributing

## Workflow

1. Fork and create feature branch.
2. Keep runtime code QuecPython-compatible.
3. Add or update docs if behavior changes.
4. Run sanitize check and mock smoke before PR.

## Pull Request Requirements

1. Scope and motivation
2. Compatibility impact (OpenClaw/Gateway/QuecPython model)
3. Risk and rollback note
4. Evidence (logs or test outputs)

## Runtime Coding Rules (device side)

1. Prefer `ujson`, `utime`, `uos`, `usocket`, `_thread`.
2. Avoid CPython-only features in runtime files.
3. Add timeout/retry/exception boundaries for network I/O.
