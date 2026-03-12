# Compatibility Matrix

## Runtime Matrix

| Item | Status |
|---|---|
| QuecPython runtime files | Supported |
| OpenClaw upstream unmodified gateway | Target baseline |
| `ws_native` connect/reconnect skeleton | Supported (rc0) |
| Full WS frame protocol | Planned |
| `mqtt_fleet` | Out of v1.0 scope |

## OpenClaw Version Policy

| OpenClaw line | Policy |
|---|---|
| stable | Mandatory smoke check before release |
| latest | Best-effort smoke check |

## Device Model Policy

- Officially supported models are published per release tag.
- Unsupported models may work but are not covered by SLA.
