# Troubleshooting

## 1. Device keeps reconnecting

Possible causes:
1. Gateway host/port unreachable.
2. Wrong network route or firewall policy.
3. Invalid URL format.

Actions:
1. Verify `OPENCLAW_WS_URL` host and port.
2. Check local network reachability.
3. Confirm gateway is running.

## 2. Runtime does not start

Possible causes:
1. Files not deployed under `/usr` correctly.
2. Missing `app` package files.

Actions:
1. Confirm `/usr/_main.py` exists.
2. Confirm `/usr/app/agent.py` exists.
3. Re-deploy full `usr_mirror` tree.

## 3. Tool rejected

Possible causes:
1. Tool not in `ALLOW_TOOLS`.
2. Tool name typo.

Actions:
1. Update `ALLOW_TOOLS` in config.
2. Check command payload `tool` field.

## 4. Release hygiene check fails

Run:

```bash
python3 tools/sanitize_check.py --root .
```

Then remove or mask sensitive content listed in output.
