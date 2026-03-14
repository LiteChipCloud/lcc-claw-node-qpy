import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "host_tools" / "qpy_device_fs_cli.py"


def _load_module():
    sys.path.insert(0, str(MODULE_PATH.parent))
    spec = importlib.util.spec_from_file_location("test_qpy_device_fs_cli", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HostReplSendLinesTest(unittest.TestCase):

    def test_repl_send_lines_does_not_force_modem_control_lines(self):
        module = _load_module()
        captured = {}

        def fake_run_powershell(script, timeout=30):
            captured["script"] = script
            return types.SimpleNamespace(stdout="ok", stderr="", returncode=0)

        with mock.patch.object(module, "run_powershell", side_effect=fake_run_powershell):
            raw = module.repl_send_lines("COM6", 921600, ["print('ok')"], timeout=5)

        self.assertEqual(raw, "ok")
        script = captured["script"]
        self.assertIn("SerialPort 'COM6',921600,'None',8,'One'", script)
        self.assertNotIn("DtrEnable", script)
        self.assertNotIn("RtsEnable", script)


if __name__ == "__main__":
    unittest.main()
