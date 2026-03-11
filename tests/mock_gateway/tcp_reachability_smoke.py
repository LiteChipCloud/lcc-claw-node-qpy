#!/usr/bin/env python3

from __future__ import annotations

import socket


def main() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect(("127.0.0.1", 18789))
        s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        data = s.recv(64)
        if not data:
            print("smoke fail: no response")
            return 1
        print("smoke pass")
        return 0
    finally:
        s.close()


if __name__ == "__main__":
    raise SystemExit(main())
