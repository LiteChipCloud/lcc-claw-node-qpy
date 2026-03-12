import utime

from app import config
from app.transport_ws_openclaw import WsNativeTransport
from app.tool_runner import ToolRunner


def _build_transport(cfg):
    if cfg.ACCESS_MODE != "ws_native":
        raise Exception("unsupported access mode in OSS v1.0: " + cfg.ACCESS_MODE)
    return WsNativeTransport(cfg)


def run():
    transport = _build_transport(config)
    runner = ToolRunner(config)

    while True:
        try:
            if not transport.online:
                ok = transport.connect()
                if not ok:
                    utime.sleep(config.RECONNECT_BACKOFF_SEC)
                    continue

            transport.tick_heartbeat()

            cmd = transport.recv_cmd(200)
            if not cmd:
                continue

            result = runner.execute(cmd)
            transport.send_result(result)

        except Exception:
            transport.close()
            utime.sleep(config.RECONNECT_BACKOFF_SEC)
