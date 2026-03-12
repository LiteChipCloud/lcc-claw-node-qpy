#!/usr/bin/env python3
"""Simple release hygiene checker for OSS package."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

TEXT_EXTS = {
    ".md",
    ".txt",
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
}

EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "venv",
}

PATTERNS = {
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "password_assignment": re.compile(r"(?i)(password|passwd|pwd|secret)\s*[:=]\s*['\"]?[^\s'\"]+"),
    "token_like": re.compile(r"(?i)(token|api[_-]?key|access[_-]?key)\s*[:=]\s*['\"][^'\"]+['\"]"),
    "private_ip": re.compile(r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b"),
    "imei_like": re.compile(r"\b\d{15}\b"),
    "iccid_like": re.compile(r"\b\d{19,20}\b"),
    "imsi_like": re.compile(r"\b\d{15}\b"),
    "github_pat": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
}

ALLOWLINE_PATTERNS = [
    re.compile(r"(?i)<token>"),
    re.compile(r"(?i)replace_with_your_token"),
    re.compile(r"(?i)your[_-]?token"),
    re.compile(r"(?i)replace_me"),
    re.compile(r"(?i)<optional-signer-token>"),
]


class Finding:
    def __init__(self, path: pathlib.Path, line_no: int, kind: str, line: str) -> None:
        self.path = path
        self.line_no = line_no
        self.kind = kind
        self.line = line


def is_text_candidate(path: pathlib.Path) -> bool:
    if path.suffix.lower() in TEXT_EXTS:
        return True
    if path.name in {"README", "LICENSE", "NOTICE", "SECURITY", "CONTRIBUTING", "CHANGELOG"}:
        return True
    return False


def iter_files(root: pathlib.Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if not is_text_candidate(path):
            continue
        yield path


def scan_file(path: pathlib.Path):
    findings = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    for i, line in enumerate(text.splitlines(), start=1):
        allowed = False
        for allow_rx in ALLOWLINE_PATTERNS:
            if allow_rx.search(line):
                allowed = True
                break
        if allowed:
            continue
        for kind, rx in PATTERNS.items():
            if rx.search(line):
                findings.append(Finding(path, i, kind, line.strip()))
    return findings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".", help="root directory to scan")
    args = p.parse_args()

    root = pathlib.Path(args.root).resolve()
    if not root.exists():
        print("root not found:", root)
        return 2

    all_findings = []
    for f in iter_files(root):
        all_findings.extend(scan_file(f))

    if not all_findings:
        print("sanitize_check: PASS")
        return 0

    print("sanitize_check: FAIL")
    for item in all_findings:
        rel = item.path.relative_to(root)
        print("%s:%d [%s] %s" % (rel, item.line_no, item.kind, item.line[:200]))

    return 1


if __name__ == "__main__":
    sys.exit(main())
