import importlib.util
import json
import sys
import threading
import time
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT_PATH = ROOT / "usr_mirror" / "app" / "transport_ws_openclaw.py"


def _install_stub_modules():
    utime = types.ModuleType("utime")
    utime._start = time.monotonic()
    utime.ticks_ms = lambda: int((time.monotonic() - utime._start) * 1000)
    utime.ticks_add = lambda value, delta: int(value) + int(delta)
    utime.ticks_diff = lambda a, b: int(a) - int(b)
    sys.modules["utime"] = utime

    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = []
    sys.modules["app"] = app_pkg

    device_auth = types.ModuleType("app.device_auth")
    device_auth.resolve_connect_security = lambda cfg, state, nonce: ({}, {"id": cfg.DEVICE_ID}, "stub")
    sys.modules["app.device_auth"] = device_auth

    json_codec = types.ModuleType("app.json_codec")
    json_codec.dumps = lambda value: json.dumps(value)
    json_codec.loads = lambda text: json.loads(text)
    sys.modules["app.json_codec"] = json_codec

    tool_probe = types.ModuleType("app.tools.tool_probe")
    tool_probe.build_runtime_telemetry = lambda cfg, state: {"online": True}
    tool_probe.wall_time_ms = lambda: int(time.time() * 1000)
    sys.modules["app.tools.tool_probe"] = tool_probe

    ws_client = types.ModuleType("app.ws_client")

    class WsClosed(Exception):
        pass

    class WsError(Exception):
        pass

    class WsTimeout(Exception):
        pass

    class WsClient(object):
        pass

    ws_client.WsClosed = WsClosed
    ws_client.WsError = WsError
    ws_client.WsTimeout = WsTimeout
    ws_client.WsClient = WsClient
    sys.modules["app.ws_client"] = ws_client


def _load_transport_module():
    _install_stub_modules()
    module_name = "test_transport_ws_openclaw_runtime"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, str(TRANSPORT_PATH))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeCfg(object):

    DEVICE_ID = "qpy-test-node"
    ACK_TIMEOUT_MS = 5000
    OUTBOX_MAX = 64
    MAX_RETRY = 3
    OUTBOX_RETRY_BACKOFF_MS = 1000


class FakeState(object):

    def __init__(self):
        self.pending_cmds = 0
        self.outbox_depth = 0
        self.result_cache_depth = 0
        self.last_outbox_error = ""
        self.last_error = ""
        self.last_error_code = ""
        self.ack_count = 0
        self.node_id = "qpy-test-node"

    def update_queue_depths(self, pending_cmds, outbox_depth, result_cache_depth):
        self.pending_cmds = int(pending_cmds)
        self.outbox_depth = int(outbox_depth)
        self.result_cache_depth = int(result_cache_depth)

    def note_ack(self):
        self.ack_count += 1

    def note_error(self, code, message):
        self.last_error_code = code or ""
        self.last_error = message or ""

    def note_outbox_error(self, message):
        self.last_outbox_error = message or ""

    def note_sent(self):
        return None

    def note_received(self):
        return None

    def note_event(self, event_name):
        return None


class TransportOutboxRaceTest(unittest.TestCase):

    def _new_transport(self):
        module = _load_transport_module()
        transport = module.WsNativeTransport(FakeCfg(), FakeState())
        transport.online = True
        transport.ws = object()
        return transport

    def test_concurrent_flush_processes_outbox_item_once(self):
        transport = self._new_transport()
        request_calls = []
        failures = []
        request_started = threading.Event()

        def fake_request(method, params, timeout_ms):
            request_calls.append((method, params.get("event")))
            request_started.set()
            time.sleep(0.05)
            return {"ok": True}

        transport._request = fake_request
        transport._queue_event("alert", {"code": "RACE_OK"}, "warning")

        def worker():
            try:
                transport.flush_outbox(1)
            except Exception as exc:
                failures.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        threads[0].start()
        self.assertTrue(request_started.wait(timeout=1.0))
        threads[1].start()
        for thread in threads:
            thread.join(timeout=2.0)

        self.assertEqual(failures, [])
        self.assertEqual(len(request_calls), 1)
        self.assertEqual(transport.state.ack_count, 1)
        self.assertEqual(transport.state.last_outbox_error, "")
        self.assertEqual(transport.state.outbox_depth, 0)
        self.assertEqual(transport._outbox, [])

    def test_failed_flush_releases_sending_flag_without_pop_error(self):
        transport = self._new_transport()
        request_calls = []
        failures = []
        request_started = threading.Event()

        def fake_request(method, params, timeout_ms):
            request_calls.append((method, params.get("event")))
            request_started.set()
            time.sleep(0.05)
            raise Exception("ack failed:test")

        transport._request = fake_request
        transport._queue_event("alert", {"code": "RACE_FAIL"}, "warning")

        def worker():
            try:
                transport.flush_outbox(1)
            except Exception as exc:
                failures.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        threads[0].start()
        self.assertTrue(request_started.wait(timeout=1.0))
        threads[1].start()
        for thread in threads:
            thread.join(timeout=2.0)

        self.assertEqual(failures, [])
        self.assertEqual(len(request_calls), 1)
        self.assertEqual(transport.state.last_error_code, "OUTBOX_SEND_FAILED")
        self.assertEqual(transport.state.last_error, "ack failed:test")
        self.assertEqual(transport.state.last_outbox_error, "ack failed:test")
        self.assertEqual(transport.state.outbox_depth, 1)
        self.assertEqual(len(transport._outbox), 1)
        self.assertEqual(transport._outbox[0].get("attempts"), 1)
        self.assertFalse(bool(transport._outbox[0].get("sending")))


if __name__ == "__main__":
    unittest.main()
