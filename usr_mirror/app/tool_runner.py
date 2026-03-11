import utime

from app.tools.tool_device_info import ToolDeviceInfo
from app.tools.tool_net_diag import ToolNetDiag


class ToolRunner(object):

    def __init__(self, cfg):
        self.cfg = cfg
        self._tools = {
            "tool_device_info": ToolDeviceInfo(cfg),
            "tool_net_diag": ToolNetDiag(cfg),
        }

    def execute(self, cmd):
        started = utime.ticks_ms()
        cmd_id = cmd.get("cmd_id", "")
        tool = cmd.get("tool", "")
        args = cmd.get("args") or {}

        if tool not in self.cfg.ALLOW_TOOLS:
            return self._error(cmd_id, tool, "UNSUPPORTED_TOOL", "tool not allowed", started)

        impl = self._tools.get(tool)
        if not impl:
            return self._error(cmd_id, tool, "UNSUPPORTED_TOOL", "tool not found", started)

        try:
            data = impl.execute(args)
            return {
                "cmd_id": cmd_id,
                "tool": tool,
                "status": "succeeded",
                "result_code": "OK",
                "data": data,
                "error": None,
                "duration_ms": utime.ticks_diff(utime.ticks_ms(), started),
            }
        except Exception as e:
            return self._error(cmd_id, tool, "EXEC_RUNTIME_ERROR", str(e), started)

    def _error(self, cmd_id, tool, code, message, started):
        return {
            "cmd_id": cmd_id,
            "tool": tool,
            "status": "failed",
            "result_code": code,
            "data": None,
            "error": message,
            "duration_ms": utime.ticks_diff(utime.ticks_ms(), started),
        }
