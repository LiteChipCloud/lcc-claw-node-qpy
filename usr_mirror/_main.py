# QuecPython entrypoint for OSS v1.0 scaffold.
# Deploy this file to /usr/_main.py.

try:
    import usys as _sys
except Exception:
    import sys as _sys


def _ensure_path(path):
    try:
        if path not in _sys.path:
            _sys.path.append(path)
    except Exception:
        pass


_ensure_path("/usr")
_ensure_path("usr")

from app.agent import run

run()
