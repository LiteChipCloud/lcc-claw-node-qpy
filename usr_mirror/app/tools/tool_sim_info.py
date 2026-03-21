from app.tools.tool_probe import gather_sim_info, wall_time_ms


class ToolSimInfo(object):

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state

    def execute(self, args):
        mask_sensitive = bool(args.get("mask_sensitive", getattr(self.cfg, "SENSITIVE_MASK", True))) if args else bool(getattr(self.cfg, "SENSITIVE_MASK", True))
        return {
            "node_id": self.state.node_id,
            "sim": gather_sim_info(mask_sensitive),
            "ts": wall_time_ms(),
        }
