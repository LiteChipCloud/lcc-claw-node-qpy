import utime


def _wall_time_ms():
    try:
        return int(utime.time() * 1000)
    except Exception:
        return 0


class RuntimeState(object):

    def __init__(self, cfg):
        self.cfg = cfg
        self.boot_ms = utime.ticks_ms()
        self.boot_wall_ms = _wall_time_ms()
        self.online = False
        self.node_id = cfg.DEVICE_ID
        self.logical_device_id = cfg.DEVICE_ID
        self.protocol = 0
        self.device_token = ""
        self.connect_attempts = 0
        self.connect_successes = 0
        self.consecutive_failures = 0
        self.safe_mode = False
        self.last_connect_ms = 0
        self.last_disconnect_ms = 0
        self.last_error = ""
        self.last_error_code = ""
        self.last_error_ms = 0
        self.last_event = ""
        self.last_event_ms = 0
        self.last_cmd_id = ""
        self.last_cmd_tool = ""
        self.last_cmd_ms = 0
        self.last_ack_ms = 0
        self.reconnect_count = 0
        self.sent_frames = 0
        self.received_frames = 0
        self.pending_cmds = 0
        self.outbox_depth = 0
        self.result_cache_depth = 0
        self.last_hello = None
        self.last_signer = None

    def note_connecting(self):
        self.connect_attempts += 1

    def note_connect(self, node_id, protocol, hello_payload):
        self.online = True
        self.node_id = node_id or self.cfg.DEVICE_ID
        self.protocol = protocol or 0
        self.connect_successes += 1
        self.consecutive_failures = 0
        self.safe_mode = False
        self.last_connect_ms = utime.ticks_ms()
        self.last_hello = hello_payload

    def note_connect_failure(self, code, message):
        self.online = False
        self.consecutive_failures += 1
        self.note_error(code, message)
        threshold = int(getattr(self.cfg, "SAFE_MODE_FAILURE_THRESHOLD", 6))
        if getattr(self.cfg, "SAFE_MODE", False) and self.consecutive_failures >= threshold:
            self.safe_mode = True

    def note_disconnect(self):
        if self.online:
            self.reconnect_count += 1
        self.online = False
        self.last_disconnect_ms = utime.ticks_ms()

    def note_error(self, code, message):
        self.last_error_code = code or ""
        self.last_error = message or ""
        self.last_error_ms = utime.ticks_ms()

    def note_event(self, event_name):
        self.last_event = event_name or ""
        self.last_event_ms = utime.ticks_ms()

    def note_command(self, cmd_id, tool):
        self.last_cmd_id = cmd_id or ""
        self.last_cmd_tool = tool or ""
        self.last_cmd_ms = utime.ticks_ms()

    def note_sent(self):
        self.sent_frames += 1

    def note_received(self):
        self.received_frames += 1

    def note_ack(self):
        self.last_ack_ms = utime.ticks_ms()

    def update_queue_depths(self, pending_cmds, outbox_depth, result_cache_depth):
        self.pending_cmds = int(pending_cmds)
        self.outbox_depth = int(outbox_depth)
        self.result_cache_depth = int(result_cache_depth)

    def snapshot(self):
        return {
            "online": self.online,
            "node_id": self.node_id,
            "logical_device_id": self.logical_device_id,
            "protocol": self.protocol,
            "boot_ms": self.boot_ms,
            "boot_wall_ms": self.boot_wall_ms,
            "last_connect_ms": self.last_connect_ms,
            "last_disconnect_ms": self.last_disconnect_ms,
            "last_error_code": self.last_error_code,
            "last_error": self.last_error,
            "last_error_ms": self.last_error_ms,
            "last_event": self.last_event,
            "last_event_ms": self.last_event_ms,
            "last_cmd_id": self.last_cmd_id,
            "last_cmd_tool": self.last_cmd_tool,
            "last_cmd_ms": self.last_cmd_ms,
            "last_ack_ms": self.last_ack_ms,
            "connect_attempts": self.connect_attempts,
            "connect_successes": self.connect_successes,
            "consecutive_failures": self.consecutive_failures,
            "reconnect_count": self.reconnect_count,
            "safe_mode": self.safe_mode,
            "sent_frames": self.sent_frames,
            "received_frames": self.received_frames,
            "pending_cmds": self.pending_cmds,
            "outbox_depth": self.outbox_depth,
            "result_cache_depth": self.result_cache_depth,
            "device_token_cached": bool(self.device_token),
            "last_signer": self.last_signer,
        }
