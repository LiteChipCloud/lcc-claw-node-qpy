import utime
try:
    import _thread
except Exception:
    _thread = None

from app.device_auth import resolve_connect_security
from app.json_codec import dumps, loads
from app.tools.tool_probe import build_runtime_telemetry, wall_time_ms
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
        self._queue_lock = _thread.allocate_lock() if bool(_thread) and hasattr(_thread, "allocate_lock") else None
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
            self._last_telemetry_ms = utime.ticks_ms()
            if self._generic_node_events_enabled():
                self._queue_event("lifecycle", {
                    "phase": "online",
                    "device_auth_mode": device_auth_mode,
                    "protocol": protocol,
                }, "info")
                self.flush_outbox(1)
            return True
        except Exception as e:
            self.state.note_connect_failure("CONNECT_FAILED", str(e))
            self.close("connect-failed")
            return False

    def close(self, reason="close"):
        if self.online and self._generic_node_events_enabled():
            self._queue_event("lifecycle", {"phase": "offline", "reason": reason}, "warning")
        self.state.note_close(reason)
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
        self.state.note_tick()
        now = utime.ticks_ms()
        hb_ms = int(getattr(self.cfg, "HEARTBEAT_INTERVAL_SEC", 15) * 1000)
        tel_ms = int(getattr(self.cfg, "TELEMETRY_INTERVAL_SEC", 60) * 1000)
        if self._generic_node_events_enabled():
            if utime.ticks_diff(now, self._last_hb_ms) >= hb_ms:
                self._last_hb_ms = now
                self._queue_event("heartbeat", self._heartbeat_payload(), "info")
            if tel_ms > 0 and utime.ticks_diff(now, self._last_telemetry_ms) >= tel_ms:
                self._last_telemetry_ms = now
                self._queue_event("telemetry", build_runtime_telemetry(self.cfg, self.state), "info")
        self.flush_outbox(1)

    def recv_cmd(self, timeout_ms, can_consume=True):
        if can_consume:
            cmd = self._pop_pending_cmd()
            if cmd:
                return cmd
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
            self._handle_incoming_frame(frame)
            if can_consume:
                cmd = self._pop_pending_cmd()
                if cmd:
                    return cmd
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
        while processed < limit:
            item = self._claim_outbox_item()
            if item is None:
                break
            try:
                response = self._request(item["method"], item["params"], int(getattr(self.cfg, "ACK_TIMEOUT_MS", 5000)))
                if not response.get("ok"):
                    error = response.get("error") or {}
                    code = error.get("code") if isinstance(error, dict) else "ACK_FAILED"
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise Exception("%s:%s" % (code or "ACK_FAILED", message or "ack failed"))
                self._finish_outbox_success(item)
                self.state.note_ack()
                processed += 1
                sent_any = True
            except Exception as e:
                self.state.note_error("OUTBOX_SEND_FAILED", str(e))
                self.state.note_outbox_error(str(e))
                if self._finish_outbox_failure(item):
                    processed += 1
                    continue
                if self._is_fatal_outbox_error(e):
                    self.close("outbox-failed")
                break
        return sent_any

    def queue_boot_event(self):
        if not self._generic_node_events_enabled():
            return False
        return self._queue_event("lifecycle", {
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
                self._consume_invoke_request(frame.get("payload") or {})
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
        if dedupe_key:
            cached = self._get_cached_result(dedupe_key)
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
        self._acquire_queue()
        try:
            self._pending_cmds.append(cmd)
            self._update_depths_locked()
        finally:
            self._release_queue()
        return None

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

    def _generic_node_events_enabled(self):
        return bool(getattr(self.cfg, "OPENCLAW_GENERIC_NODE_EVENTS", False))

    def _text_or_empty(self, value):
        if value is None:
            return ""
        try:
            return str(value).strip()
        except Exception:
            return ""

    def _bool_or_default(self, value, default_value):
        if value is None:
            return bool(default_value)
        return bool(value)

    def _alert_uplink_mode(self):
        mode = self._text_or_empty(getattr(self.cfg, "OPENCLAW_ALERT_UPLINK_MODE", "agent_request")).lower()
        if mode == "raw_node_event":
            return mode
        return "agent_request"

    def _format_business_alert_message(self, code, message, details):
        lines = ["[QuecPython Alert]"]
        device_id = self._text_or_empty(getattr(self.cfg, "DEVICE_ID", ""))
        if device_id:
            lines.append("device: " + device_id)
        code_text = self._text_or_empty(code)
        if code_text:
            lines.append("code: " + code_text)
        message_text = self._text_or_empty(message)
        if message_text:
            lines.append("message: " + message_text)
        details_text = ""
        if details not in (None, ""):
            if isinstance(details, (dict, list, tuple)):
                try:
                    details_text = dumps(details)
                except Exception:
                    details_text = self._text_or_empty(details)
            else:
                details_text = self._text_or_empty(details)
        if details_text:
            lines.append("details: " + details_text)
        return "\n".join(lines)

    def queue_agent_request(
        self,
        message,
        session_key="",
        deliver=None,
        channel="",
        to="",
        receipt=None,
        receipt_text="",
        thinking="",
        timeout_seconds=0,
    ):
        message_text = self._text_or_empty(message)
        if not message_text:
            return False

        payload = {"message": message_text}

        session_key_text = self._text_or_empty(session_key) or self._text_or_empty(
            getattr(self.cfg, "OPENCLAW_AGENT_REQUEST_SESSION_KEY", "")
        )
        if session_key_text:
            payload["sessionKey"] = session_key_text

        deliver_default = getattr(self.cfg, "OPENCLAW_AGENT_REQUEST_DELIVER", False)
        if self._bool_or_default(deliver, deliver_default):
            payload["deliver"] = True

        channel_text = self._text_or_empty(channel) or self._text_or_empty(
            getattr(self.cfg, "OPENCLAW_AGENT_REQUEST_CHANNEL", "")
        )
        if channel_text:
            payload["channel"] = channel_text

        to_text = self._text_or_empty(to) or self._text_or_empty(
            getattr(self.cfg, "OPENCLAW_AGENT_REQUEST_TO", "")
        )
        if to_text:
            payload["to"] = to_text

        receipt_default = getattr(self.cfg, "OPENCLAW_AGENT_REQUEST_RECEIPT", False)
        if self._bool_or_default(receipt, receipt_default):
            payload["receipt"] = True

        receipt_text_value = self._text_or_empty(receipt_text) or self._text_or_empty(
            getattr(self.cfg, "OPENCLAW_AGENT_REQUEST_RECEIPT_TEXT", "")
        )
        if receipt_text_value:
            payload["receiptText"] = receipt_text_value

        thinking_value = self._text_or_empty(thinking) or self._text_or_empty(
            getattr(self.cfg, "OPENCLAW_AGENT_REQUEST_THINKING", "")
        )
        if thinking_value:
            payload["thinking"] = thinking_value

        timeout_value = timeout_seconds or getattr(self.cfg, "OPENCLAW_AGENT_REQUEST_TIMEOUT_SECONDS", 0)
        if isinstance(timeout_value, int) and timeout_value > 0:
            payload["timeoutSeconds"] = timeout_value

        return self._enqueue_request("node.event", {
            "event": "agent.request",
            "payload": payload,
        }, False)

    def queue_business_alert(
        self,
        code,
        message,
        details=None,
        session_key="",
        deliver=None,
        channel="",
        to="",
        severity="warning",
    ):
        payload = {
            "code": self._text_or_empty(code),
            "message": self._text_or_empty(message),
            "details": details,
            "severity": self._text_or_empty(severity) or "warning",
        }
        if self._alert_uplink_mode() == "raw_node_event":
            return self._queue_event("alert", payload, payload["severity"])

        return self.queue_agent_request(
            self._format_business_alert_message(payload["code"], payload["message"], details),
            session_key=session_key,
            deliver=deliver,
            channel=channel,
            to=to,
        )

    def _queue_event(self, event_name, payload, severity):
        envelope = {
            "event_id": self._next_id(event_name),
            "logical_device_id": self.cfg.DEVICE_ID,
            "node_id": self.state.node_id,
            "severity": severity,
            "ts": wall_time_ms(),
            "payload": payload,
        }
        return self._enqueue_request("node.event", {
            "event": event_name,
            "payload": envelope,
        }, False)

    def _enqueue_request(self, method, params, critical):
        max_size = int(getattr(self.cfg, "OUTBOX_MAX", 64))
        dropped = False
        self._acquire_queue()
        try:
            if len(self._outbox) >= max_size:
                index = self._find_droppable_outbox_index_locked(True)
                if index < 0:
                    index = self._find_droppable_outbox_index_locked(False)
                if index >= 0:
                    self._outbox.pop(index)
                    dropped = True
                elif not critical:
                    self._update_depths_locked()
                    return False
            self._outbox.append({
                "method": method,
                "params": params,
                "critical": bool(critical),
                "attempts": 0,
                "next_attempt_ms": 0,
                "sending": False,
            })
            self._update_depths_locked()
        finally:
            self._release_queue()
        if dropped:
            self.state.note_outbox_error("OUTBOX_DROP_OLDEST")
        return True

    def _cache_result(self, key, params):
        self._acquire_queue()
        try:
            self._result_cache[key] = params
            self._result_cache_keys.append(key)
            max_size = int(getattr(self.cfg, "DEDUPE_WINDOW", 64))
            while len(self._result_cache_keys) > max_size:
                old_key = self._result_cache_keys.pop(0)
                if old_key in self._result_cache:
                    del self._result_cache[old_key]
            self._update_depths_locked()
        finally:
            self._release_queue()

    def _next_id(self, prefix):
        self._seq += 1
        return "%s_%s_%s" % (prefix, str(utime.ticks_ms()), str(self._seq))

    def _update_depths(self):
        self._acquire_queue()
        try:
            self._update_depths_locked()
        finally:
            self._release_queue()

    def _update_depths_locked(self):
        self.state.update_queue_depths(len(self._pending_cmds), len(self._outbox), len(self._result_cache_keys))

    def _acquire_queue(self):
        if self._queue_lock is not None:
            self._queue_lock.acquire()

    def _release_queue(self):
        if self._queue_lock is not None:
            self._queue_lock.release()

    def _pop_pending_cmd(self):
        cmd = None
        self._acquire_queue()
        try:
            if self._pending_cmds:
                cmd = self._pending_cmds.pop(0)
            self._update_depths_locked()
        finally:
            self._release_queue()
        return cmd

    def _get_cached_result(self, key):
        cached = None
        self._acquire_queue()
        try:
            cached = self._result_cache.get(key)
        finally:
            self._release_queue()
        return cached

    def _claim_outbox_item(self):
        item = None
        self._acquire_queue()
        try:
            if self._outbox:
                head = self._outbox[0]
                if (not head.get("sending")) and self._outbox_retry_ready(head):
                    head["sending"] = True
                    item = head
            self._update_depths_locked()
        finally:
            self._release_queue()
        return item

    def _finish_outbox_success(self, item):
        self._acquire_queue()
        try:
            self._remove_outbox_item_locked(item)
            self._update_depths_locked()
        finally:
            self._release_queue()

    def _finish_outbox_failure(self, item):
        removed = False
        self._acquire_queue()
        try:
            current = self._find_outbox_item_locked(item)
            if current is None:
                self._update_depths_locked()
                return False
            current["sending"] = False
            current["attempts"] = int(current.get("attempts") or 0) + 1
            if current["attempts"] > int(getattr(self.cfg, "MAX_RETRY", 3)):
                self._remove_outbox_item_locked(current)
                removed = True
            else:
                current["next_attempt_ms"] = utime.ticks_add(
                    utime.ticks_ms(),
                    int(getattr(self.cfg, "OUTBOX_RETRY_BACKOFF_MS", 1000)) * current["attempts"],
                )
            self._update_depths_locked()
        finally:
            self._release_queue()
        return removed

    def _find_outbox_item_locked(self, item):
        index = 0
        while index < len(self._outbox):
            if self._outbox[index] is item:
                return self._outbox[index]
            index += 1
        return None

    def _remove_outbox_item_locked(self, item):
        index = 0
        while index < len(self._outbox):
            if self._outbox[index] is item:
                self._outbox.pop(index)
                return True
            index += 1
        return False

    def _find_droppable_outbox_index_locked(self, prefer_non_critical):
        index = 0
        while index < len(self._outbox):
            item = self._outbox[index]
            if item.get("sending"):
                index += 1
                continue
            if prefer_non_critical and item.get("critical"):
                index += 1
                continue
            return index
        return -1

    def _outbox_retry_ready(self, item):
        next_attempt_ms = item.get("next_attempt_ms") or 0
        if not next_attempt_ms:
            return True
        return utime.ticks_diff(utime.ticks_ms(), next_attempt_ms) >= 0

    def _is_fatal_outbox_error(self, err):
        if isinstance(err, WsClosed):
            return True
        if isinstance(err, WsTimeout):
            return False
        if isinstance(err, WsError):
            return True
        text = str(err).lower()
        if "ack timeout" in text:
            return False
        if "ack failed" in text:
            return False
        if "websocket closed" in text or "server closed websocket" in text or "socket write failed" in text:
            return True
        return False
