# ws_native transport skeleton for QuecPython.
# Note: this scaffold only verifies TCP reachability in rc0.
# Full WebSocket frame handling will be added in v1.0 hardening.

import usocket
import utime


class WsNativeTransport(object):

    def __init__(self, cfg):
        self.cfg = cfg
        self.online = False
        self._last_hb_ms = 0

    def _parse_ws_url(self, url):
        # Minimal parser: ws://host:port/path
        u = url.strip()
        if u.startswith("ws://"):
            u = u[5:]
        elif u.startswith("wss://"):
            u = u[6:]
        p = u.find("/")
        if p >= 0:
            u = u[:p]
        if ":" in u:
            host, ps = u.split(":", 1)
            port = int(ps)
        else:
            host = u
            port = 18789
        return host, port

    def connect(self):
        host, port = self._parse_ws_url(self.cfg.OPENCLAW_WS_URL)
        s = None
        try:
            ai = usocket.getaddrinfo(host, port)
            if not ai:
                return False
            addr = ai[0][-1]
            s = usocket.socket()
            s.settimeout(3)
            s.connect(addr)
            # rc0 phase: TCP preflight only
            self.online = True
            return True
        except Exception:
            self.online = False
            return False
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass

    def close(self):
        self.online = False

    def recv_cmd(self, timeout_ms):
        # rc0 phase: no WS frame parser yet.
        utime.sleep_ms(timeout_ms)
        return None

    def send_result(self, result_payload):
        # rc0 phase placeholder.
        _ = result_payload
        return True

    def send_event(self, event_payload):
        # rc0 phase placeholder.
        _ = event_payload
        return True

    def tick_heartbeat(self):
        now = utime.ticks_ms()
        interval_ms = int(self.cfg.HEARTBEAT_INTERVAL_SEC * 1000)
        if utime.ticks_diff(now, self._last_hb_ms) >= interval_ms:
            self._last_hb_ms = now
            self.send_event({
                "event": "heartbeat",
                "device_id": self.cfg.DEVICE_ID,
                "ts": now,
            })
