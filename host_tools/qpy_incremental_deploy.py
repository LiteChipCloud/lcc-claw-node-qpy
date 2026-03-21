#!/usr/bin/env python3
"""
Manifest-driven QuecPython deployment helper for Windows host workflows.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "usr_mirror"
DEFAULT_MANIFEST = HERE / "runtime_manifest.json"
FS_CLI = HERE / "qpy_device_fs_cli.py"
DEBUG_SNAPSHOT = HERE / "qpy_debug_snapshot.py"

PLACEHOLDER_MARKERS = [
    "<openclaw_auth_token>",
    "replace_with_your_token",
    'REMOTE_SIGNER_HTTP_URL = ""',
    'OPENCLAW_AUTH_TOKEN = "replace_with_your_token"',
    'REMOTE_SIGNER_HTTP_AUTH_TOKEN = ""',
]

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def normalize_rel_path(text: str) -> str:
    value = (text or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    while value.startswith("/"):
        value = value[1:]
    return value


def run_cmd(cmd: List[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


def load_json_output(cp: subprocess.CompletedProcess[str]) -> Tuple[bool, Dict[str, Any]]:
    stdout = (cp.stdout or "").strip()
    stderr = (cp.stderr or "").strip()
    text = stdout or stderr
    try:
        payload = json.loads(text) if text else {}
    except Exception:
        payload = {
            "ok": False,
            "parse_error": "invalid_json",
            "stdout": stdout,
            "stderr": stderr,
        }
    if "ok" not in payload:
        payload["ok"] = cp.returncode == 0
    payload["exit_code"] = cp.returncode
    payload["stdout"] = stdout
    payload["stderr"] = stderr
    return bool(payload.get("ok")) and cp.returncode == 0, payload


def run_fs_cli(
    python_exe: str,
    port: str,
    auto_port: bool,
    baud: int,
    timeout: int,
    action_args: List[str],
    overall_timeout: int = 0,
) -> Tuple[bool, Dict[str, Any]]:
    cmd = [python_exe, str(FS_CLI)]
    if auto_port:
        cmd.append("--auto-port")
    else:
        cmd.extend(["--port", port])
    cmd.extend(["--baud", str(baud), "--timeout", str(timeout), "--json"])
    cmd.extend(action_args)
    final_timeout = int(overall_timeout) if int(overall_timeout) > 0 else max(timeout + 10, 40)
    return load_json_output(run_cmd(cmd, timeout=final_timeout))


def run_debug_snapshot(
    python_exe: str,
    port: str,
    auto_port: bool,
    baud: int,
) -> Dict[str, Any]:
    cmd = [python_exe, str(DEBUG_SNAPSHOT)]
    if auto_port:
        cmd.append("--auto-port")
    else:
        cmd.extend(["--port", port])
    cmd.extend(["--baud", str(baud)])
    cp = run_cmd(cmd, timeout=60)
    raw = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
    payload: Dict[str, Any] = {"ok": cp.returncode == 0, "raw": raw, "exit_code": cp.returncode}
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        body = raw[start : end + 1]
        try:
            payload["snapshot"] = json.loads(body)
        except Exception:
            payload["snapshot_parse_error"] = True
    return payload


def manifest_entries(manifest_path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    directories = data.get("directories") or []
    entries = data.get("entries") or []
    if not isinstance(directories, list) or not isinstance(entries, list):
        raise RuntimeError("Invalid manifest schema: directories/entries must be lists.")
    clean_dirs = [str(x) for x in directories if isinstance(x, str) and x.strip()]
    clean_entries = [x for x in entries if isinstance(x, dict)]
    return clean_dirs, clean_entries


def is_placeholder_config(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


def should_include(rel_path: str, includes: List[str]) -> bool:
    if not includes:
        return True
    return normalize_rel_path(rel_path) in includes


def build_push_plan(
    runtime_root: Path,
    entries: List[Dict[str, Any]],
    includes: List[str],
    config_mode: str,
    config_file: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    config_decision: Dict[str, Any] = {
        "mode": config_mode,
        "pushed": False,
        "source": "",
        "reason": "",
    }
    override_path = Path(config_file).resolve() if config_file else None
    if config_mode == "override" and not override_path:
        raise RuntimeError("--config-file is required when --config-mode=override.")
    if override_path and not override_path.is_file():
        raise RuntimeError("Config override not found: %s" % override_path)

    include_set = [normalize_rel_path(x) for x in includes if normalize_rel_path(x)]
    for entry in entries:
        rel_path = normalize_rel_path(str(entry.get("local") or ""))
        remote_dir = str(entry.get("remote_dir") or "")
        kind = str(entry.get("kind") or "runtime")
        remote_name = normalize_rel_path(str(entry.get("remote_name") or "")) or Path(rel_path).name
        if not rel_path or not remote_dir:
            raise RuntimeError("Manifest entry missing local/remote_dir: %s" % entry)
        source_path = runtime_root / rel_path
        if kind == "config":
            if config_mode == "skip":
                config_decision["reason"] = "config_mode=skip"
                continue
            if config_mode == "override":
                plan.append(
                    {
                        "kind": "config",
                        "local": str(override_path),
                        "local_rel": rel_path,
                        "remote_dir": remote_dir,
                        "remote_name": remote_name,
                    }
                )
                config_decision.update(
                    {
                        "pushed": True,
                        "source": str(override_path),
                        "reason": "explicit override",
                    }
                )
                continue
            if not should_include(rel_path, include_set):
                config_decision["reason"] = "config not selected in include set"
                continue
            if config_mode == "auto" and is_placeholder_config(source_path):
                config_decision["reason"] = "placeholder config skipped in auto mode"
                continue
            if not source_path.is_file():
                raise RuntimeError("Manifest file not found: %s" % source_path)
            plan.append(
                {
                    "kind": "config",
                    "local": str(source_path),
                    "local_rel": rel_path,
                    "remote_dir": remote_dir,
                    "remote_name": remote_name,
                }
            )
            config_decision.update(
                {
                    "pushed": True,
                    "source": str(source_path),
                    "reason": "manifest config pushed",
                }
            )
            continue

        if not should_include(rel_path, include_set):
            continue
        if not source_path.is_file():
            raise RuntimeError("Manifest file not found: %s" % source_path)
        plan.append(
            {
                "kind": kind,
                "local": str(source_path),
                "local_rel": rel_path,
                "remote_dir": remote_dir,
                "remote_name": remote_name,
            }
        )
    if config_mode in {"always", "auto"} and not config_decision["reason"] and not config_decision["pushed"]:
        config_decision["reason"] = "no config entry selected"
    return plan, config_decision


def collect_tmp_files(listings: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for remote_dir, payload in listings.items():
        for item in payload.get("rows") or []:
            name = str(item.get("name") or "")
            if name.endswith(".tmp"):
                rows.append(
                    {
                        "path": remote_dir.rstrip("/") + "/" + name if remote_dir != "/" else "/" + name,
                        "size": item.get("size"),
                    }
                )
    return rows


def verify_pushed_files(
    plan: List[Dict[str, Any]],
    listings: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    verification: List[Dict[str, Any]] = []
    row_maps: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for remote_dir, payload in listings.items():
        row_maps[remote_dir] = {
            str(item.get("name") or ""): item for item in (payload.get("rows") or []) if isinstance(item, dict)
        }
    for item in plan:
        remote_dir = item["remote_dir"]
        remote_name = item["remote_name"]
        row = row_maps.get(remote_dir, {}).get(remote_name)
        local_size = Path(item["local"]).stat().st_size
        verification.append(
            {
                "local_rel": item["local_rel"],
                "remote_path": remote_dir.rstrip("/") + "/" + remote_name if remote_dir != "/" else "/" + remote_name,
                "present": bool(row),
                "local_size": local_size,
                "remote_size": row.get("size") if row else None,
                "ok": bool(row) and (row.get("size") in {None, local_size} or row.get("size") == local_size),
            }
        )
    return verification


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Incremental QuecPython deployment helper.")
    p.add_argument("--python-exe", default=sys.executable, help="Python interpreter for helper scripts.")
    p.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT), help="Runtime root, default repo usr_mirror.")
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Manifest JSON path.")
    p.add_argument("--port", default="COM6", help="REPL port, default COM6.")
    p.add_argument("--auto-port", action="store_true", help="Auto-detect REPL port via qpy_device_fs_cli.")
    p.add_argument("--baud", type=int, default=921600, help="REPL baudrate.")
    p.add_argument("--timeout", type=int, default=35, help="Per-operation timeout seconds.")
    p.add_argument(
        "--config-mode",
        choices=["auto", "skip", "always", "override"],
        default="auto",
        help="Config push mode. Default auto skips placeholder config.",
    )
    p.add_argument("--config-file", default="", help="Explicit config override path.")
    p.add_argument(
        "--file",
        action="append",
        default=[],
        help="Relative runtime file to deploy, e.g. app/command_worker.py. Repeatable.",
    )
    p.add_argument("--start-runtime", action="store_true", help="Start /usr/_main.py after deploy.")
    p.add_argument("--snapshot", action="store_true", help="Capture debug snapshot after start-runtime.")
    p.add_argument("--fail-on-tmp", action="store_true", help="Fail if leftover .tmp files are detected.")
    p.add_argument("--json", action="store_true", help="Output JSON summary.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    runtime_root = Path(args.runtime_root).resolve()
    manifest_path = Path(args.manifest).resolve()
    if not runtime_root.is_dir():
        raise SystemExit("Runtime root not found: %s" % runtime_root)
    if not manifest_path.is_file():
        raise SystemExit("Manifest not found: %s" % manifest_path)

    directories, entries = manifest_entries(manifest_path)
    plan, config_decision = build_push_plan(
        runtime_root=runtime_root,
        entries=entries,
        includes=args.file,
        config_mode=args.config_mode,
        config_file=args.config_file,
    )

    summary: Dict[str, Any] = {
        "ok": False,
        "policy": "NO_COMMERCIAL_VERDICT",
        "runtime_root": str(runtime_root),
        "manifest": str(manifest_path),
        "config_decision": config_decision,
        "selected_files": [item["local_rel"] for item in plan],
        "mkdir": [],
        "push": [],
        "verify": {},
        "tmp_files": [],
        "tmp_clean": True,
        "verification": [],
        "start_runtime": None,
        "snapshot": None,
    }

    for remote_dir in directories:
        ok, payload = run_fs_cli(
            python_exe=args.python_exe,
            port=args.port,
            auto_port=bool(args.auto_port),
            baud=int(args.baud),
            timeout=int(args.timeout),
            action_args=["mkdir", "--path", remote_dir],
        )
        summary["mkdir"].append(payload)
        if not ok:
            print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else "mkdir failed: %s" % remote_dir)
            return 1

    for item in plan:
        local_size = Path(item["local"]).stat().st_size
        push_overall_timeout = max(int(args.timeout) + 90, 120)
        if local_size > 8192:
            push_overall_timeout = max(push_overall_timeout, int(args.timeout) + 120)
        ok, payload = run_fs_cli(
            python_exe=args.python_exe,
            port=args.port,
            auto_port=bool(args.auto_port),
            baud=int(args.baud),
            timeout=max(int(args.timeout), 35),
            overall_timeout=push_overall_timeout,
            action_args=[
                "push",
                "--local",
                item["local"],
                "--remote-dir",
                item["remote_dir"],
                "--remote-name",
                item["remote_name"],
            ],
        )
        payload["local_rel"] = item["local_rel"]
        payload["kind"] = item["kind"]
        summary["push"].append(payload)
        if not ok:
            print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else "push failed: %s" % item["local_rel"])
            return 1

    verify_payloads: Dict[str, Dict[str, Any]] = {}
    for remote_dir in directories:
        ok, payload = run_fs_cli(
            python_exe=args.python_exe,
            port=args.port,
            auto_port=bool(args.auto_port),
            baud=int(args.baud),
            timeout=int(args.timeout),
            action_args=["ls", "--path", remote_dir],
        )
        verify_payloads[remote_dir] = payload
        if not ok:
            summary["verify"][remote_dir] = payload
            print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else "verify failed: %s" % remote_dir)
            return 1
    summary["verify"] = verify_payloads
    summary["tmp_files"] = collect_tmp_files(verify_payloads)
    summary["tmp_clean"] = not summary["tmp_files"]
    summary["verification"] = verify_pushed_files(plan, verify_payloads)

    if args.start_runtime:
        ok, payload = run_fs_cli(
            python_exe=args.python_exe,
            port=args.port,
            auto_port=bool(args.auto_port),
            baud=int(args.baud),
            timeout=max(int(args.timeout), 35),
            action_args=["run", "--path", "/usr/_main.py"],
        )
        summary["start_runtime"] = payload
        if not ok:
            print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else "runtime start failed")
            return 1
        if args.snapshot:
            summary["snapshot"] = run_debug_snapshot(
                python_exe=args.python_exe,
                port=args.port,
                auto_port=bool(args.auto_port),
                baud=int(args.baud),
            )

    all_verified = all(item.get("ok") for item in summary["verification"]) if summary["verification"] else True
    summary["ok"] = all_verified and (summary["tmp_clean"] or not args.fail_on_tmp)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("Selected files: %s" % (", ".join(summary["selected_files"]) or "<none>"))
        print("Config: %s" % summary["config_decision"]["reason"])
        print("Tmp residue: %d" % len(summary["tmp_files"]))
        if summary["tmp_files"]:
            for item in summary["tmp_files"]:
                print("  - %s (%s B)" % (item["path"], item.get("size")))
        print("Verification: %s" % ("OK" if all_verified else "FAIL"))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
