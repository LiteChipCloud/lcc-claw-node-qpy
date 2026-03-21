from app.tools.tool_probe import gather_modem_info, gather_sim_info


class ToolDeviceInfo(object):

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state

    def execute(self, args):
        mask_sensitive = bool(args.get("mask_sensitive", getattr(self.cfg, "SENSITIVE_MASK", True))) if args else bool(getattr(self.cfg, "SENSITIVE_MASK", True))
        data = gather_modem_info(self.cfg, mask_sensitive)
        data["sim"] = gather_sim_info(mask_sensitive)
        data["node_id"] = self.state.node_id
        return data
