#!/usr/bin/env python3
"""Minimal mock gateway for reachability and handshake debugging."""

from __future__ import annotations

import argparse
import socket
import threading


def handle_client(conn, addr):
    try:
        data = conn.recv(4096)
        if data:
            # Basic HTTP response keeps clients from hanging on connect tests.
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18789)
    args = p.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(16)
    print("mock_gateway listening on %s:%d" % (args.host, args.port), flush=True)

    while True:
        conn, addr = srv.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
