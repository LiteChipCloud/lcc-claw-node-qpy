#!/usr/bin/env python3
"""Minimal OpenClaw gateway probe for 72h soak evidence collection.

This tool intentionally uses only the Python standard library so it can run on
gateway hosts without extra dependencies. It implements enough WebSocket client
behavior to:

1. complete the OpenClaw `connect.challenge -> connect` handshake
2. call `node.list`, `node.describe`, and `node.invoke`
3. capture asynchronous gateway events during a short observation window
4. emit sanitized JSON artifacts that are safe to store in-repo
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import platform
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_COMMANDS = [
    "qpy.runtime.status",
    "qpy.device.status",
    "qpy.tools.catalog",
]
DEFAULT_SOAK_INTERVALS = {
    "qpy.runtime.status": 300.0,
    "qpy.device.status": 900.0,
    "qpy.tools.catalog": 1800.0,
}
DEFAULT_SOAK_THRESHOLDS_MS = {
    "qpy.runtime.status": 5000,
    "qpy.device.status": 30000,
    "qpy.tools.catalog": 5000,
}
SENSITIVE_KEYS = {
    "authorization",
    "deviceid",
    "devicetoken",
    "iccid",
    "id",
    "imei",
    "imsi",
    "logicaldeviceid",
    "nonce",
    "password",
    "publickey",
    "remoteip",
    "signature",
    "token",
}


class WsError(RuntimeError):
    pass


@dataclass
class UrlParts:
    scheme: str
    host: str
    port: int
    path: str


def parse_url(raw: str) -> UrlParts:
    parsed = urlparse(raw)
    if parsed.scheme not in ("ws", "wss"):
        raise WsError("unsupported scheme: %s" % (parsed.scheme or "<empty>"))
    if not parsed.hostname:
        raise WsError("missing host in url")
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = "%s?%s" % (path, parsed.query)
    return UrlParts(parsed.scheme, parsed.hostname, port, path)


def _read_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise WsError("socket closed while reading")
        data.extend(chunk)
    return bytes(data)


def _recv_http_headers(sock: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise WsError("socket closed before websocket upgrade completed")
        data.extend(chunk)
    return bytes(data)


def _format_close_reason(payload: bytes) -> str:
    if len(payload) >= 2:
        code = int.from_bytes(payload[:2], "big")
        reason = payload[2:].decode("utf-8", errors="replace")
        return "%s:%s" % (code, reason)
    return payload.decode("utf-8", errors="replace")


class WsJsonClient:
    def __init__(self, url: str, timeout_sec: float = 10.0):
        self.url = parse_url(url)
        self.timeout_sec = timeout_sec
        self.sock: socket.socket | ssl.SSLSocket | None = None
        self._request_seq = 0
        self.buffered_events: list[dict[str, Any]] = []

    def connect(self) -> None:
        sock = socket.create_connection((self.url.host, self.url.port), self.timeout_sec)
        sock.settimeout(self.timeout_sec)
        if self.url.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=self.url.host)
            sock.settimeout(self.timeout_sec)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: lcc-claw-node-qpy/soak-probe\r\n"
            "\r\n"
        ) % (self.url.path, self.url.host, self.url.port, key)
        sock.sendall(request.encode("utf-8"))
        raw_headers = _recv_http_headers(sock)
        header_text = raw_headers.decode("utf-8", errors="replace")
        lines = header_text.split("\r\n")
        if not lines or "101" not in lines[0]:
            raise WsError("websocket upgrade failed: %s" % (lines[0] if lines else "<empty>"))
        headers = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key_name, value = line.split(":", 1)
            headers[key_name.strip().lower()] = value.strip()
        accept = headers.get("sec-websocket-accept")
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode("utf-8")).digest()).decode(
            "ascii"
        )
        if accept != expected:
            raise WsError("websocket upgrade returned unexpected accept header")
        self.sock = sock

    def close(self) -> None:
        if self.sock is None:
            return
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self.sock is None:
            raise WsError("websocket not connected")
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        length = len(payload)
        mask_key = os.urandom(4)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        masked = bytearray(payload)
        for index in range(length):
            masked[index] ^= mask_key[index % 4]
        header.extend(mask_key)
        self.sock.sendall(bytes(header) + bytes(masked))

    def send_json(self, obj: dict[str, Any]) -> None:
        self._send_frame(0x1, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _recv_frame(self, timeout_sec: float | None = None) -> tuple[int, bytes]:
        if self.sock is None:
            raise WsError("websocket not connected")
        self.sock.settimeout(timeout_sec if timeout_sec is not None else self.timeout_sec)
        first_two = _read_exact(self.sock, 2)
        byte1, byte2 = first_two[0], first_two[1]
        opcode = byte1 & 0x0F
        masked = bool(byte2 & 0x80)
        length = byte2 & 0x7F
        if length == 126:
            length = int.from_bytes(_read_exact(self.sock, 2), "big")
        elif length == 127:
            length = int.from_bytes(_read_exact(self.sock, 8), "big")
        mask_key = _read_exact(self.sock, 4) if masked else b""
        payload = bytearray(_read_exact(self.sock, length))
        if masked:
            for index in range(length):
                payload[index] ^= mask_key[index % 4]
        if opcode == 0x9:
            self._send_frame(0xA, bytes(payload))
            return self._recv_frame(timeout_sec)
        if opcode == 0x8:
            raise WsError("websocket closed: %s" % _format_close_reason(bytes(payload)))
        return opcode, bytes(payload)

    def recv_json(self, timeout_sec: float | None = None) -> dict[str, Any]:
        while True:
            opcode, payload = self._recv_frame(timeout_sec)
            if opcode != 0x1:
                continue
            try:
                return json.loads(payload.decode("utf-8"))
            except Exception as exc:  # pragma: no cover - defensive parsing
                raise WsError("invalid json frame: %s" % exc)

    def next_request_id(self, prefix: str = "req") -> str:
        self._request_seq += 1
        return "%s-%04d" % (prefix, self._request_seq)

    def request(self, method: str, params: Any, timeout_sec: float) -> dict[str, Any]:
        request_id = self.next_request_id(method.replace(".", "_"))
        self.send_json(
            {
                "type": "req",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            remaining = max(0.05, deadline - time.time())
            frame = self.recv_json(remaining)
            if frame.get("type") == "event":
                self.buffered_events.append(frame)
                continue
            if frame.get("type") == "res" and frame.get("id") == request_id:
                return frame
        raise WsError("timeout waiting for response: %s" % method)


def load_token(args: argparse.Namespace) -> str:
    if args.token:
        token = args.token.strip()
        if token:
            return token
    if args.token_env:
        token = os.environ.get(args.token_env, "").strip()
        if token:
            return token
    if args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
        if token:
            return token
    raise WsError("missing gateway token; use --token, --token-env, or --token-file")


def mask_value(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return "masked:%s" % digest


def sanitize_key(key: str) -> str:
    return key.strip().lower().replace("-", "").replace("_", "")


def sanitize_payload(value: Any, parent_key: str | None = None) -> Any:
    normalized_parent = sanitize_key(parent_key or "")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if normalized_parent in SENSITIVE_KEYS or "token" in normalized_parent or "password" in normalized_parent:
            return mask_value(value)
        if normalized_parent in {"remoteip", "ip", "nodeid", "deviceid", "logicaldeviceid"}:
            return mask_value(value)
        return value
    if isinstance(value, list):
        return [sanitize_payload(item, parent_key) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = sanitize_key(str(key))
            if normalized in SENSITIVE_KEYS or "token" in normalized or "password" in normalized:
                if isinstance(item, (str, int, float, bool)) and item not in (None, ""):
                    result[key] = mask_value(str(item))
                else:
                    result[key] = "[masked]"
                continue
            result[key] = sanitize_payload(item, str(key))
        return result
    return str(value)


def summarize_node(node: dict[str, Any]) -> dict[str, Any]:
    return sanitize_payload(
        {
            "nodeId": node.get("nodeId"),
            "displayName": node.get("displayName"),
            "platform": node.get("platform"),
            "version": node.get("version"),
            "deviceFamily": node.get("deviceFamily"),
            "caps": node.get("caps") or [],
            "commands": node.get("commands") or [],
            "paired": node.get("paired"),
            "connected": node.get("connected"),
            "connectedAtMs": node.get("connectedAtMs"),
            "remoteIp": node.get("remoteIp"),
        }
    )


def summarize_runtime_status(payload: dict[str, Any]) -> dict[str, Any]:
    payload, meta = unwrap_tool_payload(payload)
    fields = [
        "online",
        "connect_attempts",
        "connect_successes",
        "reconnect_count",
        "consecutive_failures",
        "last_error_code",
        "last_event",
        "last_cmd_tool",
        "last_probe_tool",
        "last_probe_duration_ms",
        "last_probe_timings",
        "pending_cmds",
        "outbox_depth",
        "result_cache_depth",
        "device_token_cached",
        "last_signer",
    ]
    summary = {key: payload.get(key) for key in fields if key in payload}
    summary.update(meta)
    return sanitize_payload(summary)


def summarize_tools_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    payload, meta = unwrap_tool_payload(payload)
    tool_names = []
    for item in payload.get("tools") or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("command") or item.get("id")
            if name:
                tool_names.append(name)
        elif item:
            tool_names.append(str(item))
    tool_names = sorted(set(tool_names))
    summary = {
        "tool_count": payload.get("tool_count", len(tool_names)),
        "tools": tool_names,
    }
    if "aliases" in payload:
        summary["aliases"] = payload.get("aliases")
    summary.update(meta)
    return sanitize_payload(summary)


def summarize_device_status(payload: dict[str, Any]) -> dict[str, Any]:
    payload, meta = unwrap_tool_payload(payload)
    summary: dict[str, Any] = {
        "top_level_keys": sorted(payload.keys()),
    }
    for key in ("registration", "data_context", "runtime", "network", "sim", "cell"):
        value = payload.get(key)
        if isinstance(value, dict):
            summary[key] = sanitize_payload(value)
    for key in ("probe_duration_ms", "probe_timings_ms"):
        if key in payload:
            summary[key] = sanitize_payload(payload.get(key), key)
    for key in ("online", "signal", "rat", "operator", "safe_mode"):
        if key in payload:
            summary[key] = sanitize_payload(payload.get(key), key)
    summary.update(meta)
    return summary


def unwrap_tool_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}, {}
    data = payload.get("data")
    if not isinstance(data, dict):
        return payload, {}
    meta = {}
    for key in ("status", "result_code", "duration_ms", "tool", "requested_tool", "error"):
        if key in payload:
            meta[key] = payload.get(key)
    return data, meta


def summarize_command(command: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"payload": sanitize_payload(payload)}
    if command == "qpy.runtime.status":
        return summarize_runtime_status(payload)
    if command == "qpy.device.status":
        return summarize_device_status(payload)
    if command == "qpy.tools.catalog":
        return summarize_tools_catalog(payload)
    return sanitize_payload(payload)


def summarize_event(frame: dict[str, Any]) -> dict[str, Any]:
    payload = frame.get("payload")
    inner_event = payload.get("event") if isinstance(payload, dict) else None
    summary = {
        "type": frame.get("type"),
        "event": frame.get("event"),
        "inner_event": inner_event,
    }
    if isinstance(payload, dict):
        summary["payload_keys"] = sorted(payload.keys())
        if inner_event:
            summary["payload"] = sanitize_payload(payload)
    return summary


def iso_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sanitize_error(exc: Exception) -> dict[str, Any]:
    return sanitize_payload(
        {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }
    )


def compute_duration_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "avg": None,
            "p50": None,
            "p95": None,
        }
    ordered = sorted(values)

    def pick(percentile: float) -> int:
        if len(ordered) == 1:
            return ordered[0]
        index = int(round((len(ordered) - 1) * percentile))
        return ordered[index]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "avg": int(round(sum(ordered) / len(ordered))),
        "p50": pick(0.50),
        "p95": pick(0.95),
    }


def build_sample_filename(sample_index: int, commands: list[str]) -> str:
    command_part = "+".join(command.replace(".", "_") for command in commands)
    return "%04d-%s.json" % (sample_index, command_part)


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def invoke_with_timing(
    client: WsJsonClient, node_id: str, command: str, args: argparse.Namespace
) -> dict[str, Any]:
    started_at_ms = int(time.time() * 1000)
    try:
        invoke_result = run_invoke(client, node_id, command, args)
    except Exception as exc:
        finished_at_ms = int(time.time() * 1000)
        return {
            "command": command,
            "ok": False,
            "startedAtMs": started_at_ms,
            "finishedAtMs": finished_at_ms,
            "durationMs": finished_at_ms - started_at_ms,
            "error": sanitize_error(exc),
        }

    finished_at_ms = int(time.time() * 1000)
    return {
        "command": command,
        "ok": True,
        "startedAtMs": started_at_ms,
        "finishedAtMs": finished_at_ms,
        "durationMs": finished_at_ms - started_at_ms,
        "summary": invoke_result["summary"],
    }


def run_command_session(
    args: argparse.Namespace,
    token: str,
    commands: list[str],
    event_window_sec: float,
) -> dict[str, Any]:
    session_started_at_ms = int(time.time() * 1000)
    client = WsJsonClient(args.url, timeout_sec=args.timeout_sec)
    try:
        client.connect()
        hello = connect_operator(client, token, args)
        connected_at_ms = int(time.time() * 1000)
        node_list = run_node_list(client, args)
        selected = select_node(node_list["nodes"], args)
        command_results = [
            invoke_with_timing(client, str(selected.get("nodeId")), command, args) for command in commands
        ]
        events = observe_events(client, event_window_sec)
        return {
            "ok": all(result.get("ok") for result in command_results),
            "sessionStartedAtMs": session_started_at_ms,
            "sessionFinishedAtMs": int(time.time() * 1000),
            "connectedAtMs": connected_at_ms,
            "hello": sanitize_payload(hello.get("payload") or {}),
            "selectedNode": summarize_node(selected),
            "commandResults": command_results,
            "eventCount": len(events),
            "events": [summarize_event(event) for event in events],
        }
    except Exception as exc:
        return {
            "ok": False,
            "sessionStartedAtMs": session_started_at_ms,
            "sessionFinishedAtMs": int(time.time() * 1000),
            "error": sanitize_error(exc),
            "commandResults": [],
            "eventCount": 0,
            "events": [],
        }
    finally:
        client.close()


def build_soak_summary(args: argparse.Namespace) -> dict[str, Any]:
    thresholds = {
        "qpy.runtime.status": args.runtime_threshold_ms,
        "qpy.device.status": args.device_threshold_ms,
        "qpy.tools.catalog": args.catalog_threshold_ms,
    }
    return {
        "mode": "soak",
        "capturedAt": iso_now(),
        "startedAt": iso_now(),
        "finishedAt": None,
        "config": {
            "durationSec": args.duration_sec,
            "maxSamples": args.max_samples,
            "invokeTimeoutMs": args.invoke_timeout_ms,
            "eventWindowSec": args.event_window_sec,
            "runtimeIntervalSec": args.runtime_interval_sec,
            "deviceIntervalSec": args.device_interval_sec,
            "catalogIntervalSec": args.catalog_interval_sec,
            "maxConsecutiveFailures": args.max_consecutive_failures,
            "checkpointEverySamples": args.checkpoint_every_samples,
        },
        "thresholdsMs": thresholds,
        "samples": {
            "total": 0,
            "successful": 0,
            "failed": 0,
            "consecutiveFailures": 0,
            "lastSampleFile": None,
            "lastSuccessAt": None,
            "lastFailureAt": None,
        },
        "commands": {
            command: {
                "runs": 0,
                "successful": 0,
                "failed": 0,
                "thresholdMs": threshold,
                "thresholdBreaches": 0,
                "durationsMs": [],
                "durationStats": compute_duration_stats([]),
                "lastSuccessAt": None,
                "lastFailureAt": None,
                "lastSummary": None,
                "lastError": None,
            }
            for command, threshold in thresholds.items()
        },
        "events": {
            "totalObserved": 0,
            "operatorVisibleEvents": [],
            "nodeEventVisible": False,
            "lastObservedAt": None,
        },
        "runtimeStatus": {
            "remoteSignerObserved": False,
            "reconnectCountSeries": [],
            "lastObserved": None,
        },
        "toolCatalog": {
            "baselineTools": None,
            "lastTools": None,
            "driftDetected": False,
        },
        "attentionFlags": [],
    }


def update_soak_summary(
    summary: dict[str, Any],
    sample_record: dict[str, Any],
    sample_file: Path,
    args: argparse.Namespace,
) -> None:
    samples = summary["samples"]
    samples["total"] += 1
    samples["lastSampleFile"] = str(sample_file)
    sample_finished_at = sample_record.get("finishedAt")
    sample_ok = bool(sample_record.get("ok"))
    if sample_ok:
        samples["successful"] += 1
        samples["consecutiveFailures"] = 0
        samples["lastSuccessAt"] = sample_finished_at
    else:
        samples["failed"] += 1
        samples["consecutiveFailures"] += 1
        samples["lastFailureAt"] = sample_finished_at

    summary["capturedAt"] = iso_now()

    events = sample_record.get("events") or []
    events_section = summary["events"]
    events_section["totalObserved"] += len(events)
    if events:
        events_section["lastObservedAt"] = sample_finished_at
    visible_events = set(events_section["operatorVisibleEvents"])
    for event in events:
        event_name = event.get("event")
        if isinstance(event_name, str):
            visible_events.add(event_name)
        inner_event = event.get("inner_event")
        if isinstance(event_name, str) and event_name == "node.event":
            events_section["nodeEventVisible"] = True
        if isinstance(inner_event, str):
            events_section["nodeEventVisible"] = True
    events_section["operatorVisibleEvents"] = sorted(visible_events)

    attention_flags = set(summary["attentionFlags"])
    for result in sample_record.get("commandResults") or []:
        command = result.get("command")
        if not isinstance(command, str):
            continue
        command_stats = summary["commands"].get(command)
        if not isinstance(command_stats, dict):
            continue
        command_stats["runs"] += 1
        duration_ms = result.get("durationMs")
        if isinstance(duration_ms, int):
            command_stats["durationsMs"].append(duration_ms)
            command_stats["durationStats"] = compute_duration_stats(command_stats["durationsMs"])
            threshold_ms = command_stats.get("thresholdMs")
            if isinstance(threshold_ms, int) and duration_ms > threshold_ms:
                command_stats["thresholdBreaches"] += 1
                attention_flags.add("%s latency breached %sms" % (command, threshold_ms))
        if result.get("ok"):
            command_stats["successful"] += 1
            command_stats["lastSuccessAt"] = sample_finished_at
            command_stats["lastSummary"] = result.get("summary")
        else:
            command_stats["failed"] += 1
            command_stats["lastFailureAt"] = sample_finished_at
            command_stats["lastError"] = result.get("error")
            attention_flags.add("%s failures observed" % command)

        if command == "qpy.runtime.status" and result.get("ok") and isinstance(result.get("summary"), dict):
            runtime_summary = result["summary"]
            summary["runtimeStatus"]["lastObserved"] = runtime_summary
            last_signer = runtime_summary.get("last_signer")
            if last_signer not in (None, "", False):
                summary["runtimeStatus"]["remoteSignerObserved"] = True
            reconnect_count = runtime_summary.get("reconnect_count")
            if isinstance(reconnect_count, int):
                series = summary["runtimeStatus"]["reconnectCountSeries"]
                series.append(
                    {
                        "ts": sample_finished_at,
                        "value": reconnect_count,
                    }
                )
                if len(series) > 128:
                    del series[:-128]

        if command == "qpy.tools.catalog" and result.get("ok") and isinstance(result.get("summary"), dict):
            tools = result["summary"].get("tools")
            if isinstance(tools, list):
                baseline = summary["toolCatalog"]["baselineTools"]
                if baseline is None:
                    summary["toolCatalog"]["baselineTools"] = tools
                elif tools != baseline:
                    summary["toolCatalog"]["driftDetected"] = True
                    attention_flags.add("qpy.tools.catalog drift detected")
                summary["toolCatalog"]["lastTools"] = tools

    if not events_section["nodeEventVisible"]:
        attention_flags.add("node.event frames not directly visible to operator session")
    if not summary["runtimeStatus"]["remoteSignerObserved"]:
        attention_flags.add("remote_signer_http not observed yet in runtime.status")
    summary["attentionFlags"] = sorted(attention_flags)


def next_due_commands(
    next_due: dict[str, float], now_monotonic: float, command_order: list[str]
) -> list[str]:
    due = []
    for command in command_order:
        due_at = next_due.get(command)
        if due_at is None:
            continue
        if now_monotonic >= due_at:
            due.append(command)
    return due


def schedule_next_due(
    next_due: dict[str, float], command: str, interval_sec: float, now_monotonic: float
) -> None:
    if interval_sec <= 0:
        next_due.pop(command, None)
        return
    next_due[command] = now_monotonic + interval_sec


def run_soak(args: argparse.Namespace, token: str) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    samples_dir = output_dir / "samples"
    checkpoints_dir = output_dir / "checkpoints"
    samples_dir.mkdir(parents=True, exist_ok=True)
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    summary = build_soak_summary(args)
    write_json_file(output_dir / "soak_summary.json", summary)

    command_order = list(DEFAULT_COMMANDS)
    interval_map = {
        "qpy.runtime.status": args.runtime_interval_sec,
        "qpy.device.status": args.device_interval_sec,
        "qpy.tools.catalog": args.catalog_interval_sec,
    }
    next_due = {command: time.monotonic() for command in command_order if interval_map[command] > 0}
    started_monotonic = time.monotonic()
    deadline = started_monotonic + args.duration_sec
    sample_index = 0

    while True:
        now_monotonic = time.monotonic()
        if args.max_samples > 0 and sample_index >= args.max_samples:
            break
        if now_monotonic >= deadline:
            break

        commands = next_due_commands(next_due, now_monotonic, command_order)
        if not commands:
            time.sleep(min(args.sleep_granularity_sec, max(0.05, deadline - now_monotonic)))
            continue

        sample_index += 1
        event_window_sec = args.event_window_sec if "qpy.runtime.status" in commands else 0.0
        sample_started_at = iso_now()
        session_result = run_command_session(args, token, commands, event_window_sec)
        finished_at = iso_now()
        sample_record = {
            "sampleIndex": sample_index,
            "startedAt": sample_started_at,
            "finishedAt": finished_at,
            "requestedCommands": commands,
            "ok": bool(session_result.get("ok")),
            "eventWindowSec": event_window_sec,
            "selectedNode": session_result.get("selectedNode"),
            "error": session_result.get("error"),
            "commandResults": session_result.get("commandResults") or [],
            "eventCount": session_result.get("eventCount", 0),
            "events": session_result.get("events") or [],
        }
        sample_file = samples_dir / build_sample_filename(sample_index, commands)
        write_json_file(sample_file, sample_record)
        update_soak_summary(summary, sample_record, sample_file, args)
        write_json_file(output_dir / "soak_summary.json", summary)

        if args.checkpoint_every_samples > 0 and sample_index % args.checkpoint_every_samples == 0:
            checkpoint_payload = dict(summary)
            checkpoint_payload["checkpointAt"] = iso_now()
            checkpoint_payload["checkpointSample"] = sample_index
            write_json_file(
                checkpoints_dir / ("checkpoint-%04d.json" % sample_index), checkpoint_payload
            )

        now_after_sample = time.monotonic()
        for command in commands:
            schedule_next_due(next_due, command, interval_map[command], now_after_sample)

        if summary["samples"]["consecutiveFailures"] >= args.max_consecutive_failures:
            summary["attentionFlags"] = sorted(
                set(summary["attentionFlags"])
                | {
                    "aborted after %d consecutive failed samples"
                    % summary["samples"]["consecutiveFailures"]
                }
            )
            break

    summary["capturedAt"] = iso_now()
    summary["finishedAt"] = iso_now()
    write_json_file(output_dir / "soak_summary.json", summary)
    return summary


def run_recovery_check(args: argparse.Namespace, token: str) -> dict[str, Any]:
    started_at = iso_now()
    started_monotonic = time.monotonic()
    attempts = []
    while time.monotonic() - started_monotonic < args.deadline_sec:
        session = run_command_session(args, token, [args.command], args.event_window_sec)
        sample = {
            "attempt": len(attempts) + 1,
            "ts": iso_now(),
            "ok": bool(session.get("ok")),
            "error": session.get("error"),
            "selectedNode": session.get("selectedNode"),
            "commandResults": session.get("commandResults") or [],
            "eventCount": session.get("eventCount", 0),
            "events": session.get("events") or [],
        }
        attempts.append(sample)
        if session.get("ok"):
            elapsed_ms = int(round((time.monotonic() - started_monotonic) * 1000))
            return {
                "mode": "recovery-check",
                "startedAt": started_at,
                "finishedAt": iso_now(),
                "elapsedMs": elapsed_ms,
                "targetMs": args.target_ms,
                "targetMet": elapsed_ms <= args.target_ms,
                "attempts": attempts,
            }
        time.sleep(args.poll_sec)

    return {
        "mode": "recovery-check",
        "startedAt": started_at,
        "finishedAt": iso_now(),
        "elapsedMs": int(round((time.monotonic() - started_monotonic) * 1000)),
        "targetMs": args.target_ms,
        "targetMet": False,
        "attempts": attempts,
        "error": {
            "type": "RecoveryTimeout",
            "message": "no successful %s within %.1fs" % (args.command, args.deadline_sec),
        },
    }


def connect_operator(client: WsJsonClient, token: str, args: argparse.Namespace) -> dict[str, Any]:
    deadline = time.time() + args.timeout_sec
    challenge = None
    while time.time() < deadline:
        remaining = max(0.05, deadline - time.time())
        frame = client.recv_json(remaining)
        if frame.get("type") == "event":
            client.buffered_events.append(frame)
            if frame.get("event") == "connect.challenge":
                challenge = frame
                break
    if challenge is None:
        raise WsError("timed out waiting for connect.challenge")
    response = client.request(
        "connect",
        {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": args.client_id,
                "displayName": args.client_display_name,
                "version": args.client_version,
                "platform": args.client_platform,
                "mode": args.client_mode,
            },
            "caps": [],
            "auth": {"token": token},
            "role": args.role,
            "scopes": list(args.scope),
        },
        args.timeout_sec,
    )
    if not response.get("ok"):
        raise WsError("gateway connect failed: %s" % json.dumps(response.get("error")))
    return response


def run_node_list(client: WsJsonClient, args: argparse.Namespace) -> dict[str, Any]:
    response = client.request("node.list", {}, args.timeout_sec)
    if not response.get("ok"):
        raise WsError("node.list failed: %s" % json.dumps(response.get("error")))
    payload = response.get("payload") or {}
    nodes = payload.get("nodes") or []
    if not isinstance(nodes, list):
        raise WsError("node.list returned non-list nodes payload")
    return {
        "ts": payload.get("ts"),
        "nodes": [node for node in nodes if isinstance(node, dict)],
    }


def select_node(nodes: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    if args.node_id:
        for node in nodes:
            if node.get("nodeId") == args.node_id:
                return node
        raise WsError("node not found: %s" % args.node_id)
    filtered = []
    for node in nodes:
        if args.node_platform and node.get("platform") != args.node_platform:
            continue
        if args.node_family and node.get("deviceFamily") != args.node_family:
            continue
        if args.connected_only and not node.get("connected"):
            continue
        filtered.append(node)
    if not filtered:
        raise WsError("no node matched the requested filters")
    return filtered[0]


def run_describe(client: WsJsonClient, node_id: str, args: argparse.Namespace) -> dict[str, Any]:
    response = client.request("node.describe", {"nodeId": node_id}, args.timeout_sec)
    if not response.get("ok"):
        raise WsError("node.describe failed: %s" % json.dumps(response.get("error")))
    payload = response.get("payload")
    if isinstance(payload, dict):
        return payload
    if isinstance(response, dict) and isinstance(response.get("payload"), dict):
        return response["payload"]
    return response


def run_invoke(client: WsJsonClient, node_id: str, command: str, args: argparse.Namespace) -> dict[str, Any]:
    response = client.request(
        "node.invoke",
        {
            "nodeId": node_id,
            "command": command,
            "params": {},
            "timeoutMs": args.invoke_timeout_ms,
            "idempotencyKey": "soak-%s-%d" % (command.replace(".", "-"), int(time.time() * 1000)),
        },
        max(args.timeout_sec, args.invoke_timeout_ms / 1000.0 + 5),
    )
    if not response.get("ok"):
        raise WsError("node.invoke failed for %s: %s" % (command, json.dumps(response.get("error"))))
    payload = response.get("payload") or {}
    if isinstance(payload, dict) and "payload" in payload:
        payload = payload.get("payload")
    return {
        "command": command,
        "response": response,
        "summary": summarize_command(command, payload),
    }


def observe_events(client: WsJsonClient, seconds: float) -> list[dict[str, Any]]:
    if seconds <= 0:
        events = client.buffered_events[:]
        client.buffered_events = []
        return events
    deadline = time.time() + seconds
    while time.time() < deadline:
        remaining = max(0.05, deadline - time.time())
        try:
            frame = client.recv_json(remaining)
        except socket.timeout:
            break
        except TimeoutError:
            break
        except OSError as exc:
            if isinstance(exc, socket.timeout):
                break
            raise
        except WsError as exc:
            if "timed out" in str(exc).lower():
                break
            raise
        if frame.get("type") == "event":
            client.buffered_events.append(frame)
    events = client.buffered_events[:]
    client.buffered_events = []
    return events


def build_burnin_result(client: WsJsonClient, args: argparse.Namespace) -> dict[str, Any]:
    burnin_started_at_ms = int(time.time() * 1000)
    node_list = run_node_list(client, args)
    selected = select_node(node_list["nodes"], args)
    describe_payload = run_describe(client, str(selected.get("nodeId")), args)
    iterations = []
    for index in range(args.iterations):
        started_at = int(time.time() * 1000)
        command_results = []
        for command in args.command:
            command_results.append(
                invoke_with_timing(client, str(selected.get("nodeId")), command, args)
            )
        events = observe_events(client, args.event_window_sec)
        iterations.append(
            {
                "iteration": index + 1,
                "startedAtMs": started_at,
                "commands": command_results,
                "eventCount": len(events),
                "events": [summarize_event(event) for event in events],
            }
        )
        if index + 1 < args.iterations and args.sleep_sec > 0:
            time.sleep(args.sleep_sec)
    return {
        "startedAtMs": burnin_started_at_ms,
        "nodeSelection": summarize_node(selected),
        "nodeDescribe": sanitize_payload(describe_payload),
        "iterations": iterations,
    }


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", required=True, help="Gateway WebSocket URL, e.g. ws://127.0.0.1:18789")
    parser.add_argument("--token", help="Gateway token (discouraged for shell history)")
    parser.add_argument("--token-file", help="Path to a file that contains the gateway token")
    parser.add_argument("--token-env", default="OPENCLAW_GATEWAY_TOKEN", help="Environment variable that contains the gateway token")
    parser.add_argument("--timeout-sec", type=float, default=10.0, help="RPC timeout in seconds")
    parser.add_argument("--client-id", default="cli")
    parser.add_argument("--client-display-name", default="qpy-soak-probe")
    parser.add_argument("--client-version", default="0.1.0")
    parser.add_argument("--client-mode", default="cli")
    parser.add_argument("--client-platform", default=platform.system().lower())
    parser.add_argument("--role", default="operator", choices=["operator", "node"])
    parser.add_argument("--scope", action="append", default=["operator.admin"])
    parser.add_argument("--node-id", help="Explicit nodeId")
    parser.add_argument("--node-platform", default="quectel")
    parser.add_argument("--node-family", default="quecpython")
    parser.add_argument("--connected-only", action="store_true", help="Require the selected node to be connected")
    parser.add_argument("--json-output", help="Write sanitized JSON result to this file")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenClaw gateway soak probe")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    node_list = subparsers.add_parser("node-list", help="List available nodes")
    add_common_args(node_list)

    describe = subparsers.add_parser("node-describe", help="Describe a selected node")
    add_common_args(describe)

    invoke = subparsers.add_parser("node-invoke", help="Invoke one or more node commands")
    add_common_args(invoke)
    invoke.add_argument("--command", action="append", required=True, help="Command to invoke")
    invoke.add_argument("--invoke-timeout-ms", type=int, default=30000)
    invoke.add_argument("--event-window-sec", type=float, default=0.0)

    burnin = subparsers.add_parser("burnin", help="Run a short burn-in loop for soak preflight")
    add_common_args(burnin)
    burnin.add_argument(
        "--command",
        action="append",
        default=None,
        help="Command to invoke each iteration (defaults to runtime/device/catalog trio)",
    )
    burnin.add_argument("--iterations", type=int, default=3)
    burnin.add_argument("--sleep-sec", type=float, default=30.0)
    burnin.add_argument("--event-window-sec", type=float, default=95.0)
    burnin.add_argument("--invoke-timeout-ms", type=int, default=30000)

    soak = subparsers.add_parser("soak", help="Run a long-lived periodic soak sampler")
    add_common_args(soak)
    soak.add_argument("--output-dir", required=True, help="Directory for samples and summaries")
    soak.add_argument("--duration-sec", type=float, default=72 * 3600.0)
    soak.add_argument("--max-samples", type=int, default=0, help="0 means unlimited until duration")
    soak.add_argument("--runtime-interval-sec", type=float, default=DEFAULT_SOAK_INTERVALS["qpy.runtime.status"])
    soak.add_argument("--device-interval-sec", type=float, default=DEFAULT_SOAK_INTERVALS["qpy.device.status"])
    soak.add_argument("--catalog-interval-sec", type=float, default=DEFAULT_SOAK_INTERVALS["qpy.tools.catalog"])
    soak.add_argument("--event-window-sec", type=float, default=95.0)
    soak.add_argument("--invoke-timeout-ms", type=int, default=30000)
    soak.add_argument("--runtime-threshold-ms", type=int, default=DEFAULT_SOAK_THRESHOLDS_MS["qpy.runtime.status"])
    soak.add_argument("--device-threshold-ms", type=int, default=DEFAULT_SOAK_THRESHOLDS_MS["qpy.device.status"])
    soak.add_argument("--catalog-threshold-ms", type=int, default=DEFAULT_SOAK_THRESHOLDS_MS["qpy.tools.catalog"])
    soak.add_argument("--max-consecutive-failures", type=int, default=6)
    soak.add_argument("--checkpoint-every-samples", type=int, default=12)
    soak.add_argument("--sleep-granularity-sec", type=float, default=1.0)

    recovery = subparsers.add_parser("recovery-check", help="Poll for post-restart command recovery")
    add_common_args(recovery)
    recovery.add_argument("--command", default="qpy.runtime.status")
    recovery.add_argument("--poll-sec", type=float, default=5.0)
    recovery.add_argument("--deadline-sec", type=float, default=120.0)
    recovery.add_argument("--target-ms", type=int, default=30000)
    recovery.add_argument("--event-window-sec", type=float, default=0.0)
    recovery.add_argument("--invoke-timeout-ms", type=int, default=30000)

    args = parser.parse_args(argv)
    if args.mode == "burnin" and not args.command:
        args.command = list(DEFAULT_COMMANDS)
    return args


def emit_result(result: dict[str, Any], args: argparse.Namespace) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    token = load_token(args)
    if args.mode == "soak":
        try:
            soak_result = run_soak(args, token)
            emit_result(soak_result, args)
            return 0
        except Exception as exc:
            sys.stderr.write("gateway_soak_probe error: %s\n" % exc)
            return 1

    if args.mode == "recovery-check":
        try:
            recovery_result = run_recovery_check(args, token)
            emit_result(recovery_result, args)
            return 0 if "error" not in recovery_result else 1
        except Exception as exc:
            sys.stderr.write("gateway_soak_probe error: %s\n" % exc)
            return 1

    client = WsJsonClient(args.url, timeout_sec=args.timeout_sec)
    try:
        client.connect()
        hello = connect_operator(client, token, args)
        if args.mode == "node-list":
            node_list = run_node_list(client, args)
            emit_result(
                {
                    "mode": args.mode,
                    "connectedAtMs": int(time.time() * 1000),
                    "hello": sanitize_payload(hello.get("payload") or {}),
                    "nodes": [summarize_node(node) for node in node_list["nodes"]],
                },
                args,
            )
            return 0

        node_list = run_node_list(client, args)
        selected = select_node(node_list["nodes"], args)
        if args.mode == "node-describe":
            describe_payload = run_describe(client, str(selected.get("nodeId")), args)
            emit_result(
                {
                    "mode": args.mode,
                    "connectedAtMs": int(time.time() * 1000),
                    "hello": sanitize_payload(hello.get("payload") or {}),
                    "selectedNode": summarize_node(selected),
                    "nodeDescribe": sanitize_payload(describe_payload),
                },
                args,
            )
            return 0

        if args.mode == "node-invoke":
            results = []
            for command in args.command:
                invoke_result = run_invoke(client, str(selected.get("nodeId")), command, args)
                events = observe_events(client, args.event_window_sec)
                results.append(
                    {
                        "command": command,
                        "summary": invoke_result["summary"],
                        "eventCount": len(events),
                        "events": [summarize_event(event) for event in events],
                    }
                )
            emit_result(
                {
                    "mode": args.mode,
                    "connectedAtMs": int(time.time() * 1000),
                    "hello": sanitize_payload(hello.get("payload") or {}),
                    "selectedNode": summarize_node(selected),
                    "results": results,
                },
                args,
            )
            return 0

        if args.mode == "burnin":
            burnin_result = build_burnin_result(client, args)
            emit_result(
                {
                    "mode": args.mode,
                    "connectedAtMs": int(time.time() * 1000),
                    "hello": sanitize_payload(hello.get("payload") or {}),
                    "burnin": burnin_result,
                },
                args,
            )
            return 0

        raise WsError("unsupported mode: %s" % args.mode)
    except Exception as exc:
        sys.stderr.write("gateway_soak_probe error: %s\n" % exc)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
