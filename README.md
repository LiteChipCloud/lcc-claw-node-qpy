# lcc-claw-node-qpy

QuecPython device runtime for connecting to upstream OpenClaw Gateway without gateway source modification.

## Positioning

This repository is the community (OSS) edition of the QuecPython runtime.

- Target: upstream OpenClaw users (unmodified gateway)
- Current scope: `ws_native` minimum closed loop
- Out of scope in v1.0: enterprise-only `mqtt_fleet + adapter + lcc-server`

Maintainer: 芯寰云（上海）科技有限公司

## v1.0 scope

1. Device bootstrap and main loop (`/usr/_main.py`)
2. OpenClaw WebSocket native transport (`connect`, heartbeat, reconnect)
3. Minimal tool runner and safe built-in tools
4. Mock gateway smoke test assets
5. Security/sanitization and open-source whitelist rules

## Repository layout

```text
usr_mirror/
  _main.py
  app/
    agent.py
    config.py
    transport_ws_openclaw.py
    tool_runner.py
    tools/
examples/
  config.ws_native.example.py
docs/
  quickstart.md
  compatibility-matrix.md
  troubleshooting.md
  open-source-whitelist.md
  sanitization-rules.md
tools/
  sanitize_check.py
tests/
  mock_gateway/
```

## Quick start

1. Read [docs/quickstart.md](docs/quickstart.md)
2. Copy [examples/config.ws_native.example.py](examples/config.ws_native.example.py) to your device config file
3. Deploy `usr_mirror/*` to device `/usr`
4. Run `/usr/_main.py`

## Security and open-source hygiene

- Run `python3 tools/sanitize_check.py --root .` before publishing
- Follow [docs/open-source-whitelist.md](docs/open-source-whitelist.md)
- Follow [docs/sanitization-rules.md](docs/sanitization-rules.md)

## License

MIT License. See [LICENSE](LICENSE).

## Status

- Version: `v1.0.0-rc0` (scaffold phase)
- Focus date window: 2026-03 to 2026-04
