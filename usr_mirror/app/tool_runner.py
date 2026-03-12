import utime

from app.tools.tool_cell_info import ToolCellInfo
from app.tools.tool_device_info import ToolDeviceInfo
from app.tools.tool_device_status import ToolDeviceStatus
from app.tools.tool_net_diag import ToolNetDiag
from app.tools.tool_runtime_status import ToolRuntimeStatus
from app.tools.tool_sim_info import ToolSimInfo
from app.tools.tool_tools_catalog import ToolToolsCatalog


class ToolRunner(object):

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state
        self._entries = []
        self._name_to_entry = {}
        self._register(
            "qpy.device.info",
            ToolDeviceInfo(cfg, state),
            "读取设备基础身份、型号、固件与 SIM 概况",
            ["tool_device_info"],
            "device",
        )
        self._register(
            "qpy.device.status",
            ToolDeviceStatus(cfg, state),
            "聚合设备、SIM、网络、PDP、运行时状态",
            [],
            "device",
        )
        self._register(
            "qpy.net.diag",
            ToolNetDiag(cfg, state),
            "输出网络注册、数据通道、小区与排障建议",
            ["tool_net_diag"],
            "network",
        )
        self._register(
            "qpy.sim.info",
            ToolSimInfo(cfg, state),
            "读取 SIM 卡状态、IMSI、ICCID 等信息",
            [],
            "network",
        )
        self._register(
            "qpy.cell.info",
            ToolCellInfo(cfg, state),
            "读取服务小区与邻区信息",
            [],
            "network",
        )
        self._register(
            "qpy.runtime.status",
            ToolRuntimeStatus(cfg, state),
            "查看运行时会话、重连、队列与错误状态",
            [],
            "runtime",
        )
        self._register(
            "qpy.tools.catalog",
            ToolToolsCatalog(cfg, state, self.catalog_entries),
            "查看当前设备声明的全部工具和别名",
            [],
            "runtime",
        )

    def _register(self, name, impl, summary, aliases, category):
        entry = {
            "name": name,
            "impl": impl,
            "summary": summary,
            "aliases": aliases or [],
            "category": category,
        }
        self._entries.append(entry)
        self._name_to_entry[name] = entry
        for alias in entry["aliases"]:
            self._name_to_entry[alias] = entry

    def catalog_entries(self):
        return self._entries

    def _allowed(self, entry, requested_tool):
        allow_tools = getattr(self.cfg, "ALLOW_TOOLS", []) or []
        if "*" in allow_tools:
            return True
        if requested_tool in allow_tools:
            return True
        if entry["name"] in allow_tools:
            return True
        for alias in entry["aliases"]:
            if alias in allow_tools:
                return True
        return False

    def execute(self, cmd):
        started = utime.ticks_ms()
        request_id = cmd.get("request_id", "")
        tool = cmd.get("tool", "")
        args = cmd.get("args") or {}

        entry = self._name_to_entry.get(tool)
        if not entry:
            return self._error(request_id, tool, tool, "UNSUPPORTED_TOOL", "tool not found", started)
        if not self._allowed(entry, tool):
            return self._error(request_id, tool, entry["name"], "UNSUPPORTED_TOOL", "tool not allowed", started)

        self.state.note_command(request_id, entry["name"])
        try:
            data = entry["impl"].execute(args)
            return {
                "cmd_id": request_id,
                "requested_tool": tool,
                "tool": entry["name"],
                "status": "succeeded",
                "result_code": "OK",
                "data": data,
                "error": None,
                "duration_ms": utime.ticks_diff(utime.ticks_ms(), started),
            }
        except Exception as e:
            return self._error(request_id, tool, entry["name"], "EXEC_RUNTIME_ERROR", str(e), started)

    def _error(self, request_id, requested_tool, tool, code, message, started):
        return {
            "cmd_id": request_id,
            "requested_tool": requested_tool,
            "tool": tool,
            "status": "failed",
            "result_code": code,
            "data": None,
            "error": message,
            "duration_ms": utime.ticks_diff(utime.ticks_ms(), started),
        }
