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
    code = (
        "def _dump(v):\n"
        " try:\n"
        "  import ujson\n"
        "  print(ujson.dumps(v))\n"
        " except Exception:\n"
        "  print(v)\n"
    )
    lines = [
        'import sys',
        'sys.path.append(\'/usr\') if \'/usr\' not in sys.path else None',
        'sys.path.append(\'usr\') if \'usr\' not in sys.path else None',
        '_code=%r' % code,
        'exec(_code)',
        'import app.agent as agent',
        '_dump(agent.debug_snapshot())',
    ]
    raw = repl_send_lines(port, args.baud, lines, timeout=40, line_delay_ms=45, settle_ms=1500)
    print(raw)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
