from app.tools.tool_probe import gather_runtime_info, wall_time_ms


class ToolRuntimeStatus(object):

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state

    def execute(self, args):
        _ = args
        runtime = gather_runtime_info(self.cfg, self.state)
        runtime["ts"] = wall_time_ms()
        return runtime
