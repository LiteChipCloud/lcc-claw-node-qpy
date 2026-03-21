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
3. Prefer incremental re-deploy for the missing files instead of blindly re-pushing the full bundle.

## 3. Tool rejected

Possible causes:
1. Tool not in `ALLOW_TOOLS`.
2. Tool name typo.

Actions:
1. Update `ALLOW_TOOLS` in config.
2. Check command payload `tool` field.

## 4. Config overwritten by placeholder file

Possible causes:
1. A host-side deploy script pushed the example `config.py` to `/usr/app/config.py`.
2. The device was switched to a different Gateway or token by mistake.

Actions:
1. Compare the live `/usr/app/config.py` with your expected runtime config.
2. Re-push the real config explicitly; do not rely on template files.
3. Re-run a light smoke such as `qpy.runtime.status` before any full deploy retry.
4. Prefer `QPY_PUSH_CONFIG=override` with `scripts/deploy_to_device.ps1` instead of editing the template file in place.

## 5. `.tmp` files remain after deploy

Possible causes:
1. Large-file REPL push did not finish cleanly.
2. The host-side deploy flow mixed file transfer, config push, and runtime start in one step.

Actions:
1. Record which `.tmp` files remain and their sizes.
2. Re-push only the affected live file instead of the full bundle.
3. Verify the runtime with `qpy.runtime.status` and `qpy.tools.catalog`.
4. Do not delete live files blindly during recovery.
5. If you want `.tmp` to block the deploy verdict, run `host_tools/qpy_incremental_deploy.py --fail-on-tmp`.
6. If you are operating Mac -> Windows over SSH, prefer `./scripts/windows_qpyctl.sh deploy --file ...` so the toolkit stays resident on Windows and only runtime deltas are synced.
7. To inspect stale residue safely first, run `./scripts/windows_qpyctl.sh cleanup-tmp --json`.
8. Only run `./scripts/windows_qpyctl.sh cleanup-tmp --apply` after you confirm the paired live files are present and no deploy is in progress.

## 6. Large file deploy times out

Possible causes:
1. The file itself is valid, but the REPL transport needs a larger execution budget.
2. The default deploy timeout is sized for normal runtime files, not the largest diagnostic bundles.

Actions:
1. Retry with a larger timeout, for example `./scripts/windows_qpyctl.sh deploy --file app/tools/tool_probe.py --timeout 120`.
2. Keep the resident toolkit updated with `./scripts/windows_qpyctl.sh install`.
3. Re-check the target file size on the device after the retry.
4. If old failed attempts left stale `.tmp`, inspect them with `./scripts/windows_qpyctl.sh cleanup-tmp --json` before the next recovery pass.

## 7. Windows resident toolkit missing or outdated

Possible causes:
1. Windows host does not yet have the fixed toolkit directory.
2. Local host tools changed, but Windows still has an older copy.

Actions:
1. Run `./scripts/windows_qpyctl.sh install`.
2. Re-run `./scripts/windows_qpyctl.sh snapshot` to confirm the resident toolkit is callable.
3. Then continue with `./scripts/windows_qpyctl.sh deploy --file ...`.

## 8. Windows COM port opens, but REPL stays silent

Possible causes:
1. A Windows-hosted `.NET SerialPort` flow forces `DTR/RTS` before `Open()`, and the Quectel driver returns `A device attached to the system is not functioning`.
2. After a device repower, `COM6` may still `OPEN_OK` without forced modem-control lines, but the REPL readback can remain `<empty>`.

Actions:
1. Update the resident toolkit with the latest `host_tools/qpy_device_fs_cli.py`; the current fix removes forced `DTR/RTS` toggling from `repl_send_lines()`.
2. Verify the distinction explicitly:
   - `windows-com6-open-no-dtr.txt` should show `OPEN_OK`.
   - `windows-com6-open-with-dtr.txt` should show the driver failure.
   - `windows-repl-echo-probe.txt` or `./scripts/windows_qpyctl.sh snapshot --port COM6` may still show `<empty>` while the port itself is open.
3. Treat `<empty>` as a separate `REPL-silent` state instead of a generic port-open failure.
4. While REPL is silent, fall back to Gateway-side `qpy.device.status` / `qpy.runtime.status` probes for runtime counters and outbox health.
5. Do not reintroduce `DTR/RTS` forcing in ad hoc PowerShell or Python serial helpers unless you have revalidated the exact Windows driver behavior on the current host.

## 9. Release hygiene check fails

Run:

```bash
python3 tools/sanitize_check.py --root .
```

Then remove or mask sensitive content listed in output.
