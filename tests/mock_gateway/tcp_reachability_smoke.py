#!/usr/bin/env python3

from __future__ import annotations

import base64
import os
import socket
import struct


def recv_http_headers(sock):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            return b""
        data.extend(chunk)
    return bytes(data)


def recv_ws_text(sock):
    header = sock.recv(2)
    if not header:
        return ""
    byte1, byte2 = struct.unpack("!BB", header)
    length = byte2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
    payload = bytearray()
    while len(payload) < length:
        payload.extend(sock.recv(length - len(payload)))
    if (byte1 & 0x0F) != 0x1:
        return ""
    return payload.decode("utf-8")


def main() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect(("127.0.0.1", 18789))
        sec_key = base64.b64encode(os.urandom(16)).decode("utf-8")
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost:18789\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ) % sec_key
        s.sendall(request.encode("utf-8"))
        headers = recv_http_headers(s)
        if b"101 Switching Protocols" not in headers:
            print("smoke fail: missing websocket upgrade")
            return 1
        first_frame = recv_ws_text(s)
        if "connect.challenge" not in first_frame:
            print("smoke fail: missing connect challenge")
            return 1
        print("smoke pass")
        return 0
    finally:
        s.close()


if __name__ == "__main__":
    raise SystemExit(main())
