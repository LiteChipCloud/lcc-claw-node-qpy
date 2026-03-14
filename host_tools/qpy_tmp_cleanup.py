#!/usr/bin/env python3
"""
Report and optionally clean stale temporary files left by REPL deploy flows.

Default mode is report-only. A file becomes a delete candidate only when:
1. It matches a known temp pattern in a scanned directory.
2. A paired live file exists beside it.
3. The live file is a normal file entry.

Rollback backups are excluded by default and require --include-rollback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
FS_CLI = HERE / "qpy_device_fs_cli.py"
DEFAULT_SCAN_PATHS = ["/usr/app", "/usr/app/tools"]

TMP_PATTERNS = [
    ("upload_tmp", re.compile(r"^(?P<live>.+)\.upload_\d+\.tmp$")),
    ("plain_tmp", re.compile(r"^(?P<live>.+)\.tmp$")),
    ("rollback_bak", re.compile(r"^(?P<live>.+)\.rollback_\d+\.bak$")),
]

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def normalize_remote_path(path: str) -> str:
    text = (path or "").strip().replace("\\", "/")
    if not text.startswith("/"):
        text = "/" + text
    text = re.sub(r"/{2,}", "/", text)
    return text.rstrip("/") or "/"


def join_remote_path(remote_dir: str, name: str) -> str:
    base = normalize_remote_path(remote_dir)
    if base == "/":
        return normalize_remote_path("/" + name)
    return normalize_remote_path(base + "/" + name)


def run_cmd(cmd: List[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
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
    final_timeout = int(overall_timeout) if int(overall_timeout) > 0 else max(timeout + 12, 45)
    return load_json_output(run_cmd(cmd, timeout=final_timeout))


def classify_temp_name(name: str) -> Tuple[str, str]:
    for kind, pattern in TMP_PATTERNS:
        match = pattern.match(name or "")
        if match:
            live_name = str(match.group("live") or "").strip()
            if live_name and not live_name.endswith(".tmp") and not live_name.endswith(".bak"):
                return kind, live_name
    return "", ""


def summarize_scan_rows(remote_dir: str, rows: List[Dict[str, Any]], include_rollback: bool) -> List[Dict[str, Any]]:
    live_files: Dict[str, Dict[str, Any]] = {}
    for item in rows:
        name = str(item.get("name") or "")
        if str(item.get("type") or "") != "file":
            continue
        kind, _ = classify_temp_name(name)
        if kind:
            continue
        live_files[name] = item

    entries: List[Dict[str, Any]] = []
    for item in rows:
        name = str(item.get("name") or "")
        if str(item.get("type") or "") != "file":
            continue
        kind, live_name = classify_temp_name(name)
        if not kind:
            continue
        entry: Dict[str, Any] = {
            "dir": normalize_remote_path(remote_dir),
            "path": join_remote_path(remote_dir, name),
            "name": name,
            "kind": kind,
            "temp_size": item.get("size"),
            "live_name": live_name,
            "live_path": join_remote_path(remote_dir, live_name),
            "live_exists": False,
            "live_size": -1,
            "decision": "skip",
            "reason": "",
        }
        live_item = live_files.get(live_name)
        if kind == "rollback_bak" and not include_rollback:
            entry["reason"] = "rollback excluded by default"
            entries.append(entry)
            continue
        if not live_item:
            entry["reason"] = "paired live file missing"
            entries.append(entry)
            continue
        entry["live_exists"] = True
        entry["live_size"] = live_item.get("size", -1)
        entry["decision"] = "delete_candidate"
        entry["reason"] = "paired live file exists"
        entries.append(entry)
    return entries


def print_human(payload: Dict[str, Any]) -> None:
    print("Cleanup mode: %s" % ("apply" if payload.get("apply") else "report-only"))
    print("Port: %s" % payload.get("port"))
    print("Paths: %s" % ", ".join(payload.get("paths") or []))
    print("Candidates: %s" % payload.get("summary", {}).get("delete_candidates", 0))
    print("Skipped: %s" % payload.get("summary", {}).get("skipped", 0))
    if payload.get("apply"):
        print("Deleted: %s" % payload.get("summary", {}).get("deleted", 0))
        print("Delete failed: %s" % payload.get("summary", {}).get("delete_failed", 0))
    for entry in payload.get("entries") or []:
        print(
            "- %(decision)s | %(path)s | %(reason)s | live=%(live_path)s size %(live_size)s"
            % entry
        )
    for item in payload.get("scan_errors") or []:
        print("- scan_error | %s | %s" % (item.get("path"), item.get("reason")))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report or clean stale deploy temp files on device.")
    parser.add_argument("--port", default="COM6", help="REPL port, default COM6.")
    parser.add_argument("--auto-port", action="store_true", help="Auto-detect REPL port.")
    parser.add_argument("--baud", type=int, default=115200, help="REPL baudrate.")
    parser.add_argument("--timeout", type=int, default=25, help="Per-operation timeout seconds.")
    parser.add_argument("--python", default="py", help="Python launcher on Windows, default py.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    parser.add_argument("--apply", action="store_true", help="Actually remove delete candidates.")
    parser.add_argument(
        "--include-rollback",
        action="store_true",
        help="Also treat rollback backups as cleanup candidates when paired live files exist.",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Directory to scan. Repeatable. Default scans /usr/app and /usr/app/tools.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    timeout = max(8, int(args.timeout))
    paths = [normalize_remote_path(p) for p in (args.path or DEFAULT_SCAN_PATHS)]
    python_exe = args.python or "py"

    scan_errors: List[Dict[str, Any]] = []
    entries: List[Dict[str, Any]] = []
    ok = True

    for remote_dir in paths:
        scan_ok, payload = run_fs_cli(
            python_exe=python_exe,
            port=args.port,
            auto_port=bool(args.auto_port),
            baud=int(args.baud),
            timeout=timeout,
            action_args=["ls", "--path", remote_dir],
            overall_timeout=max(timeout + 15, 45),
        )
        if not scan_ok:
            ok = False
            scan_errors.append(
                {
                    "path": remote_dir,
                    "reason": payload.get("stderr") or payload.get("stdout") or "ls failed",
                }
            )
            continue
        entries.extend(
            summarize_scan_rows(
                remote_dir=remote_dir,
                rows=payload.get("rows") or [],
                include_rollback=bool(args.include_rollback),
            )
        )

    if args.apply and ok:
        for entry in entries:
            if entry.get("decision") != "delete_candidate":
                continue
            rm_ok, rm_payload = run_fs_cli(
                python_exe=python_exe,
                port=args.port,
                auto_port=bool(args.auto_port),
                baud=int(args.baud),
                timeout=timeout,
                action_args=["rm", "--path", str(entry.get("path") or "")],
                overall_timeout=max(timeout + 15, 45),
            )
            entry["apply_ok"] = rm_ok
            if rm_ok:
                entry["decision"] = "deleted"
                entry["reason"] = "removed by cleanup"
            else:
                ok = False
                entry["decision"] = "delete_failed"
                entry["reason"] = rm_payload.get("stderr") or rm_payload.get("stdout") or "rm failed"

    summary = {
        "total_temp_entries": len(entries),
        "delete_candidates": len([x for x in entries if x.get("decision") in {"delete_candidate", "deleted"}]),
        "skipped": len([x for x in entries if x.get("decision") == "skip"]),
        "deleted": len([x for x in entries if x.get("decision") == "deleted"]),
        "delete_failed": len([x for x in entries if x.get("decision") == "delete_failed"]),
    }
    payload = {
        "ok": ok,
        "policy": "REPORT_ONLY_DEFAULT",
        "apply": bool(args.apply),
        "port": "auto" if args.auto_port else args.port,
        "baud": int(args.baud),
        "paths": paths,
        "include_rollback": bool(args.include_rollback),
        "summary": summary,
        "scan_errors": scan_errors,
        "entries": entries,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
