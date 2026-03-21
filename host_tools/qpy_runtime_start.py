#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from qpy_device_fs_cli import repl_send_lines, resolve_port  # noqa: E402

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--port', default='COM6')
    p.add_argument('--auto-port', action='store_true')
    p.add_argument('--baud', type=int, default=921600)
    args = p.parse_args()
    port = resolve_port(args.port, args.auto_port, timeout=15)
    lines = [
        'import sys',
        'import _thread',
        'sys.path.append(\'/usr\') if \'/usr\' not in sys.path else None',
        'sys.path.append(\'usr\') if \'usr\' not in sys.path else None',
        '[sys.modules.pop(_k) for _k in list(sys.modules.keys()) if _k == \'app\' or _k.startswith(\'app.\')]',
        'import app.agent as agent',
        '_thread.start_new_thread(agent.run, ())',
        'print(\'runtime_thread_started\')',
    ]
    raw = repl_send_lines(port, args.baud, lines, timeout=40, line_delay_ms=45, settle_ms=1500)
    print(raw)
    return 0 if 'runtime_thread_started' in raw else 1


if __name__ == '__main__':
    raise SystemExit(main())
