import utime

from app import config
from app.command_worker import CommandWorker
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


def queue_agent_request(
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
    global _LAST_EXCEPTION
    if _LAST_TRANSPORT is None or not hasattr(_LAST_TRANSPORT, "queue_agent_request"):
        return False
    try:
        _LAST_EXCEPTION = ""
        return bool(_LAST_TRANSPORT.queue_agent_request(
            message,
            session_key=session_key,
            deliver=deliver,
            channel=channel,
            to=to,
            receipt=receipt,
            receipt_text=receipt_text,
            thinking=thinking,
            timeout_seconds=timeout_seconds,
        ))
    except Exception as e:
        _LAST_EXCEPTION = str(e)
        return False


def emit_business_alert(
    code,
    message,
    details=None,
    session_key="",
    deliver=None,
    channel="",
    to="",
    severity="warning",
):
    global _LAST_EXCEPTION
    if _LAST_TRANSPORT is None or not hasattr(_LAST_TRANSPORT, "queue_business_alert"):
        return False
    try:
        _LAST_EXCEPTION = ""
        return bool(_LAST_TRANSPORT.queue_business_alert(
            code,
            message,
            details=details,
            session_key=session_key,
            deliver=deliver,
            channel=channel,
            to=to,
            severity=severity,
        ))
    except Exception as e:
        _LAST_EXCEPTION = str(e)
        return False


def run():
    global _LAST_STATE
    global _LAST_TRANSPORT
    global _LAST_EXCEPTION
    state = RuntimeState(config)
    transport = _build_transport(config, state)
    runner = ToolRunner(config, state)
    worker = CommandWorker(runner, state)
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
            if worker.available:
                done = worker.poll_result()
                if done:
                    transport.send_result(done.get("cmd") or {}, done.get("result") or {})

                if worker.can_accept():
                    cmd = transport.recv_cmd(int(getattr(config, "READ_POLL_MS", 200)), True)
                    if cmd:
                        if not worker.submit(cmd):
                            state.note_inflight_start(cmd.get("request_id"), cmd.get("tool"))
                            result = runner.execute(cmd)
                            state.note_inflight_finish(result.get("status"), result.get("result_code"))
                            transport.send_result(cmd, result)
                    continue

                transport.recv_cmd(int(getattr(config, "READ_POLL_MS", 200)), False)
                continue

            cmd = transport.recv_cmd(int(getattr(config, "READ_POLL_MS", 200)), True)
            if not cmd:
                continue

            state.note_inflight_start(cmd.get("request_id"), cmd.get("tool"))
            result = runner.execute(cmd)
            state.note_inflight_finish(result.get("status"), result.get("result_code"))
            transport.send_result(cmd, result)

        except Exception as e:
            _LAST_EXCEPTION = str(e)
            state.note_error("RUNTIME_LOOP_ERROR", str(e))
            transport.close("loop-error")
            utime.sleep(config.RECONNECT_BACKOFF_SEC)
