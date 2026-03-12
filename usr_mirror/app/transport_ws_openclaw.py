import utime

from app.device_auth import resolve_connect_security
from app.json_codec import dumps, loads
from app.tools.tool_probe import build_device_status, wall_time_ms
from app.ws_client import WsClient, WsClosed, WsError, WsTimeout


class WsNativeTransport(object):

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state
        self.ws = None
        self.online = False
        self._seq = 0
        self._last_hb_ms = 0
        self._last_telemetry_ms = 0
        self._pending_cmds = []
        self._outbox = []
        self._result_cache = {}
        self._result_cache_keys = []
        self._update_depths()

    def connect(self):
        self.close("reconnect")
        self.state.note_connecting()
        ws = WsClient()
        try:
            ws.connect(self.cfg.OPENCLAW_WS_URL, int(getattr(self.cfg, "CONNECT_TIMEOUT_SEC", 8)))
            self.ws = ws
            challenge = self._wait_connect_challenge()
            nonce = challenge.get("nonce") if isinstance(challenge, dict) else None
            if not nonce:
                raise Exception("connect challenge missing nonce")

            auth, device, device_auth_mode = resolve_connect_security(self.cfg, self.state, nonce)
            params = self._build_connect_params(auth, device)
            response = self._request("connect", params, int(getattr(self.cfg, "ACK_TIMEOUT_MS", 5000)))
            if not response.get("ok"):
                error = response.get("error") or {}
                code = error.get("code") if isinstance(error, dict) else "CONNECT_FAILED"
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise Exception("%s:%s" % (code or "CONNECT_FAILED", message or "connect failed"))

            payload = response.get("payload") or {}
            auth_info = payload.get("auth") or {}
            device_token = auth_info.get("deviceToken")
            if device_token:
                self.state.device_token = device_token
            protocol = payload.get("protocol") or 0
            node_id = self.cfg.DEVICE_ID
            if isinstance(device, dict) and device.get("id"):
                node_id = device.get("id")
            self.online = True
            self.state.note_connect(node_id, protocol, payload)
            self._last_hb_ms = 0
            self._last_telemetry_ms = 0
            self._queue_event("lifecycle", {
                "phase": "online",
                "device_auth_mode": device_auth_mode,
                "protocol": protocol,
            }, "info")
            self._queue_event("telemetry", build_device_status(self.cfg, self.state, bool(getattr(self.cfg, "SENSITIVE_MASK", True))), "info")
            self.flush_outbox(2)
            return True
        except Exception as e:
            self.state.note_connect_failure("CONNECT_FAILED", str(e))
            self.close("connect-failed")
            return False

    def close(self, reason="close"):
        if self.online:
            self._queue_event("lifecycle", {"phase": "offline", "reason": reason}, "warning")
        self.online = False
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = None
        self.state.note_disconnect()
        self._update_depths()

    def tick(self):
        now = utime.ticks_ms()
        hb_ms = int(getattr(self.cfg, "HEARTBEAT_INTERVAL_SEC", 15) * 1000)
        tel_ms = int(getattr(self.cfg, "TELEMETRY_INTERVAL_SEC", 60) * 1000)
        if utime.ticks_diff(now, self._last_hb_ms) >= hb_ms:
            self._last_hb_ms = now
            self._queue_event("heartbeat", self._heartbeat_payload(), "info")
        if tel_ms > 0 and utime.ticks_diff(now, self._last_telemetry_ms) >= tel_ms:
            self._last_telemetry_ms = now
            self._queue_event("telemetry", build_device_status(self.cfg, self.state, bool(getattr(self.cfg, "SENSITIVE_MASK", True))), "info")
        self.flush_outbox(1)

    def recv_cmd(self, timeout_ms):
        if self._pending_cmds:
            self._update_depths()
            return self._pending_cmds.pop(0)
        if not self.online or self.ws is None:
            return None

        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms)
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            remaining = utime.ticks_diff(deadline, utime.ticks_ms())
            try:
                frame = self._recv_frame(remaining)
            except WsTimeout:
                return None
            if frame is None:
                return None
            cmd = self._handle_incoming_frame(frame)
            if cmd:
                return cmd
            if self._pending_cmds:
                self._update_depths()
                return self._pending_cmds.pop(0)
        return None

    def send_result(self, cmd, result_payload):
        params = self._build_result_params(cmd, result_payload)
        cache_key = cmd.get("dedupe_key") or cmd.get("request_id")
        if cache_key:
            self._cache_result(cache_key, params)
        self._enqueue_request("node.invoke.result", params, True)
        return self.flush_outbox(1)

    def flush_outbox(self, limit):
        if not self.online or self.ws is None:
            self._update_depths()
            return False
        sent_any = False
        processed = 0
        while self._outbox and processed < limit:
            item = self._outbox[0]
            try:
                response = self._request(item["method"], item["params"], int(getattr(self.cfg, "ACK_TIMEOUT_MS", 5000)))
                if not response.get("ok"):
                    error = response.get("error") or {}
                    code = error.get("code") if isinstance(error, dict) else "ACK_FAILED"
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise Exception("%s:%s" % (code or "ACK_FAILED", message or "ack failed"))
                self._outbox.pop(0)
                self.state.note_ack()
                processed += 1
                sent_any = True
                self._update_depths()
            except Exception as e:
                item["attempts"] += 1
                self.state.note_error("OUTBOX_SEND_FAILED", str(e))
                if item["attempts"] > int(getattr(self.cfg, "MAX_RETRY", 3)):
                    self._outbox.pop(0)
                    processed += 1
                    self._update_depths()
                    continue
                self.close("outbox-failed")
                break
        return sent_any

    def queue_boot_event(self):
        self._queue_event("lifecycle", {
            "phase": "boot",
            "firmware": getattr(self.cfg, "FW_VERSION", ""),
            "device_name": getattr(self.cfg, "DEVICE_NAME", ""),
        }, "info")

    def _wait_connect_challenge(self):
        deadline = utime.ticks_add(utime.ticks_ms(), int(getattr(self.cfg, "CONNECT_TIMEOUT_SEC", 8) * 1000))
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            remaining = utime.ticks_diff(deadline, utime.ticks_ms())
            frame = self._recv_frame(remaining)
            if not isinstance(frame, dict):
                continue
            if frame.get("type") == "event" and frame.get("event") == "connect.challenge":
                self.state.note_event("connect.challenge")
                return frame.get("payload") or {}
        raise Exception("connect challenge timeout")

    def _build_connect_params(self, auth, device):
        params = {
            "minProtocol": int(getattr(self.cfg, "OPENCLAW_MIN_PROTOCOL", 3)),
            "maxProtocol": int(getattr(self.cfg, "OPENCLAW_MAX_PROTOCOL", 3)),
            "client": {
                "id": getattr(self.cfg, "OPENCLAW_CLIENT_ID", "node-host"),
                "displayName": getattr(self.cfg, "OPENCLAW_CLIENT_DISPLAY_NAME", "QuecPython OpenClaw Node"),
                "version": getattr(self.cfg, "FW_VERSION", "v1.0.0"),
                "platform": getattr(self.cfg, "OPENCLAW_CLIENT_PLATFORM", "quectel"),
                "deviceFamily": getattr(self.cfg, "OPENCLAW_CLIENT_DEVICE_FAMILY", "quecpython"),
                "mode": getattr(self.cfg, "OPENCLAW_CLIENT_MODE", "node"),
            },
            "role": getattr(self.cfg, "OPENCLAW_ROLE", "node"),
            "scopes": list(getattr(self.cfg, "OPENCLAW_SCOPES", [])),
            "caps": list(getattr(self.cfg, "OPENCLAW_CAPS", [])),
            "commands": list(getattr(self.cfg, "OPENCLAW_COMMANDS", [])),
            "permissions": getattr(self.cfg, "OPENCLAW_PERMISSIONS", {}),
            "userAgent": getattr(self.cfg, "OPENCLAW_USER_AGENT", "lcc-claw-node-qpy/1.0.0"),
        }
        if auth:
            params["auth"] = auth
        if device:
            params["device"] = device
        return params

    def _request(self, method, params, timeout_ms):
        request_id = self._next_id(method)
        frame = {
            "type": "req",
            "id": request_id,
            "method": method,
            "params": params,
        }
        self._send_frame(frame)
        return self._await_response(request_id, timeout_ms)

    def _await_response(self, request_id, timeout_ms):
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms)
        while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
            remaining = utime.ticks_diff(deadline, utime.ticks_ms())
            frame = self._recv_frame(remaining)
            if not isinstance(frame, dict):
                continue
            if frame.get("type") == "res" and frame.get("id") == request_id:
                return frame
            self._handle_incoming_frame(frame)
        raise Exception("ack timeout")

    def _recv_frame(self, timeout_ms):
        if self.ws is None:
            raise WsClosed("websocket closed")
        text = self.ws.recv_text(timeout_ms)
        frame = loads(text)
        self.state.note_received()
        return frame

    def _send_frame(self, frame):
        if self.ws is None:
            raise WsClosed("websocket closed")
        self.ws.send_text(dumps(frame))
        self.state.note_sent()

    def _handle_incoming_frame(self, frame):
        frame_type = frame.get("type")
        if frame_type == "event":
            event_name = frame.get("event")
            self.state.note_event(event_name)
            if event_name == "node.invoke.request":
                return self._consume_invoke_request(frame.get("payload") or {})
            return None
        return None

    def _consume_invoke_request(self, payload):
        request_id = payload.get("id")
        node_id = payload.get("nodeId") or self.state.node_id
        command = payload.get("command") or ""
        params = {}
        raw_json = payload.get("paramsJSON")
        if raw_json not in (None, ""):
            try:
                params = loads(raw_json)
            except Exception:
                self._enqueue_request("node.invoke.result", {
                    "id": request_id,
                    "nodeId": node_id,
                    "ok": False,
                    "error": {
                        "code": "INVALID_PARAMS",
                        "message": "paramsJSON parse failed",
                    },
                }, True)
                return None
        dedupe_key = payload.get("idempotencyKey") or request_id
        if dedupe_key and dedupe_key in self._result_cache:
            cached = self._result_cache.get(dedupe_key)
            if cached:
                self._enqueue_request("node.invoke.result", cached, True)
            return None
        cmd = {
            "request_id": request_id,
            "node_id": node_id,
            "tool": command,
            "args": params if isinstance(params, dict) else {"value": params},
            "timeout_ms": payload.get("timeoutMs") or int(getattr(self.cfg, "MAX_CMD_EXEC_SEC", 10) * 1000),
            "idempotency_key": payload.get("idempotencyKey"),
            "dedupe_key": dedupe_key,
        }
        self._pending_cmds.append(cmd)
        self._update_depths()
        return self._pending_cmds.pop(0)

    def _build_result_params(self, cmd, result_payload):
        params = {
            "id": cmd.get("request_id"),
            "nodeId": cmd.get("node_id") or self.state.node_id,
            "ok": result_payload.get("status") == "succeeded",
        }
        if params["ok"]:
            params["payload"] = result_payload
        else:
            params["error"] = {
                "code": result_payload.get("result_code") or "EXEC_RUNTIME_ERROR",
                "message": result_payload.get("error") or "command failed",
            }
        return params

    def _heartbeat_payload(self):
        runtime = self.state.snapshot()
        return {
            "event_id": self._next_id("heartbeat"),
            "logical_device_id": self.cfg.DEVICE_ID,
            "node_id": self.state.node_id,
            "severity": "info",
            "ts": wall_time_ms(),
            "payload": {
                "online": runtime.get("online"),
                "reconnect_count": runtime.get("reconnect_count"),
                "last_error_code": runtime.get("last_error_code"),
                "last_cmd_tool": runtime.get("last_cmd_tool"),
            },
        }

    def _queue_event(self, event_name, payload, severity):
        envelope = {
            "event_id": self._next_id(event_name),
            "logical_device_id": self.cfg.DEVICE_ID,
            "node_id": self.state.node_id,
            "severity": severity,
            "ts": wall_time_ms(),
            "payload": payload,
        }
        self._enqueue_request("node.event", {
            "event": event_name,
            "payload": envelope,
        }, False)

    def _enqueue_request(self, method, params, critical):
        if len(self._outbox) >= int(getattr(self.cfg, "OUTBOX_MAX", 64)):
            index = 0
            while index < len(self._outbox):
                if not self._outbox[index].get("critical"):
                    self._outbox.pop(index)
                    break
                index += 1
            if len(self._outbox) >= int(getattr(self.cfg, "OUTBOX_MAX", 64)):
                self._outbox.pop(0)
        self._outbox.append({
            "method": method,
            "params": params,
            "critical": bool(critical),
            "attempts": 0,
        })
        self._update_depths()

    def _cache_result(self, key, params):
        self._result_cache[key] = params
        self._result_cache_keys.append(key)
        max_size = int(getattr(self.cfg, "DEDUPE_WINDOW", 64))
        while len(self._result_cache_keys) > max_size:
            old_key = self._result_cache_keys.pop(0)
            if old_key in self._result_cache:
                del self._result_cache[old_key]
        self._update_depths()

    def _next_id(self, prefix):
        self._seq += 1
        return "%s_%s_%s" % (prefix, str(utime.ticks_ms()), str(self._seq))

    def _update_depths(self):
        self.state.update_queue_depths(len(self._pending_cmds), len(self._outbox), len(self._result_cache_keys))
