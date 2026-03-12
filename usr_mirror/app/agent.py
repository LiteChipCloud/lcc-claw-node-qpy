import utime

from app import config
from app.runtime_state import RuntimeState
from app.tool_runner import ToolRunner
from app.transport_ws_openclaw import WsNativeTransport

_LAST_STATE = None
_LAST_TRANSPORT = None
_LAST_EXCEPTION = ""


def _build_transport(cfg, state):
    if cfg.ACCESS_MODE != "ws_native":
        raise Exception("unsupported access mode in OSS v1.0: " + cfg.ACCESS_MODE)
    return WsNativeTransport(cfg, state)


def debug_snapshot():
    state_snapshot = None
    if _LAST_STATE is not None:
        try:
            state_snapshot = _LAST_STATE.snapshot()
        except Exception:
            state_snapshot = None
    return {
        "has_state": _LAST_STATE is not None,
        "has_transport": _LAST_TRANSPORT is not None,
        "online": bool(getattr(_LAST_TRANSPORT, "online", False)) if _LAST_TRANSPORT is not None else False,
        "last_exception": _LAST_EXCEPTION,
        "state": state_snapshot,
    }


def run():
    global _LAST_STATE
    global _LAST_TRANSPORT
    global _LAST_EXCEPTION
    state = RuntimeState(config)
    transport = _build_transport(config, state)
    runner = ToolRunner(config, state)
    _LAST_STATE = state
    _LAST_TRANSPORT = transport
    _LAST_EXCEPTION = ""
    transport.queue_boot_event()

    while True:
        try:
            if not transport.online:
                ok = transport.connect()
                if not ok:
                    cooldown = config.RECONNECT_BACKOFF_SEC
                    if state.safe_mode:
                        cooldown = int(getattr(config, "SAFE_MODE_COOLDOWN_SEC", cooldown))
                    utime.sleep(cooldown)
                    continue

            transport.tick()
            cmd = transport.recv_cmd(int(getattr(config, "READ_POLL_MS", 200)))
            if not cmd:
                continue

            result = runner.execute(cmd)
            transport.send_result(cmd, result)

        except Exception as e:
            _LAST_EXCEPTION = str(e)
            state.note_error("RUNTIME_LOOP_ERROR", str(e))
            transport.close("loop-error")
            utime.sleep(config.RECONNECT_BACKOFF_SEC)
