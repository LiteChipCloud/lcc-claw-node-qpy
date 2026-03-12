#!/usr/bin/env python3
"""Mock OpenClaw Gateway for local QuecPython runtime smoke tests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def read_http_request(conn):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed before headers")
        data.extend(chunk)
    return bytes(data)


def parse_headers(raw):
    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\r\n")
    headers = {}
    for line in lines[1:]:
        if not line:
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def websocket_accept(key):
    digest = hashlib.sha1((key + GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_text(conn, payload):
    body = payload.encode("utf-8")
    header = bytearray()
    header.append(0x81)
    length = len(body)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    conn.sendall(bytes(header) + body)


def recv_frame(conn):
    header = conn.recv(2)
    if not header:
        raise ConnectionError("socket closed")
    byte1, byte2 = struct.unpack("!BB", header)
    length = byte2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", conn.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", conn.recv(8))[0]
    masked = bool(byte2 & 0x80)
    mask = conn.recv(4) if masked else b""
    payload = bytearray()
    while len(payload) < length:
        payload.extend(conn.recv(length - len(payload)))
    if masked:
        for idx in range(length):
            payload[idx] ^= mask[idx % 4]
    return byte1 & 0x0F, payload.decode("utf-8")


def send_json(conn, obj):
    send_text(conn, json.dumps(obj, ensure_ascii=False))


def handle_client(conn, addr, args):
    conn.settimeout(30)
    node_id = "mock-node"
    try:
        raw = read_http_request(conn)
        headers = parse_headers(raw)
        sec_key = headers.get("sec-websocket-key")
        if not sec_key:
            conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            return
        response = [
            "HTTP/1.1 101 Switching Protocols",
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Accept: %s" % websocket_accept(sec_key),
            "",
            "",
        ]
        conn.sendall("\r\n".join(response).encode("utf-8"))
        nonce = "mock-%s" % os.urandom(4).hex()
        send_json(conn, {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": nonce, "ts": int(time.time() * 1000)},
        })

        invoke_sent = False
        while True:
            opcode, text = recv_frame(conn)
            if opcode == 0x8:
                break
            frame = json.loads(text)
            if frame.get("type") != "req":
                continue
            method = frame.get("method")
            if method == "connect":
                params = frame.get("params") or {}
                device = params.get("device") or {}
                node_id = device.get("id") or params.get("client", {}).get("id") or node_id
                print("[mock] connect from %s node=%s" % (addr, node_id), flush=True)
                send_json(conn, {
                    "type": "res",
                    "id": frame.get("id"),
                    "ok": True,
                    "payload": {
                        "type": "hello-ok",
                        "protocol": 3,
                        "policy": {"tickIntervalMs": 15000},
                        "auth": {
                            "deviceToken": "mock-device-token",
                            "role": params.get("role", "node"),
                            "scopes": params.get("scopes", []),
                        },
                    },
                })
                if args.invoke_command and not invoke_sent:
                    invoke_sent = True
                    time.sleep(args.invoke_delay_sec)
                    send_json(conn, {
                        "type": "event",
                        "event": "node.invoke.request",
                        "payload": {
                            "id": "mock-invoke-1",
                            "nodeId": node_id,
                            "command": args.invoke_command,
                            "paramsJSON": args.invoke_params,
                            "timeoutMs": args.invoke_timeout_ms,
                            "idempotencyKey": "mock-invoke-1",
                        },
                    })
            elif method in ("node.event", "node.invoke.result"):
                print("[mock] %s %s" % (method, json.dumps(frame.get("params"), ensure_ascii=False)), flush=True)
                send_json(conn, {
                    "type": "res",
                    "id": frame.get("id"),
                    "ok": True,
                    "payload": {"ok": True},
                })
            else:
                send_json(conn, {
                    "type": "res",
                    "id": frame.get("id"),
                    "ok": False,
                    "error": {"code": "MOCK_UNSUPPORTED", "message": "unsupported method"},
                })
    except Exception as exc:
        print("[mock] client error %s %s" % (addr, exc), flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18789)
    parser.add_argument("--invoke-command", default="qpy.runtime.status")
    parser.add_argument("--invoke-params", default="{}")
    parser.add_argument("--invoke-timeout-ms", type=int, default=10000)
    parser.add_argument("--invoke-delay-sec", type=float, default=1.0)
    args = parser.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(16)
    print("mock_gateway listening on %s:%d" % (args.host, args.port), flush=True)

    while True:
        conn, addr = srv.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr, args), daemon=True)
        thread.start()


if __name__ == "__main__":
    main()
