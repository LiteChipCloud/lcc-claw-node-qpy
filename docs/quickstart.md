# QuickStart (Official OpenClaw, No Gateway Source Modification)

## 1. Prerequisites

1. OpenClaw Gateway is installed and running.
2. You have a reachable gateway URL and valid token.
3. QuecPython module can run scripts under `/usr`.

## 2. Prepare Device Files

1. Copy `usr_mirror/_main.py` to device `/usr/_main.py`
2. Copy `usr_mirror/app/*` to device `/usr/app/`
3. Edit `/usr/app/config.py` with your URL/token/device_id

## 3. Start Runtime

Run on device:

```python
import _main
```

## 4. Expected Behavior

1. Device attempts to connect using `OPENCLAW_WS_URL`.
2. If target is reachable, runtime enters online loop.
3. Heartbeat event is generated periodically.
4. On failure, runtime reconnects with fixed backoff.

## 5. Notes for rc0

- Current rc0 transport verifies TCP reachability only.
- Full WebSocket frame handling is planned in v1.0 hardening.
- Use `tests/mock_gateway/mock_gateway.py` for local development verification.
