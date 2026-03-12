from app.tools.tool_probe import build_recommendations, gather_cell_info, gather_data_context, gather_network_info, gather_runtime_info, gather_sim_info, wall_time_ms


class ToolNetDiag(object):

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state

    def execute(self, args):
        mask_sensitive = bool(args.get("mask_sensitive", getattr(self.cfg, "SENSITIVE_MASK", True))) if args else bool(getattr(self.cfg, "SENSITIVE_MASK", True))
        sim_info = gather_sim_info(mask_sensitive)
        network_info = gather_network_info()
        data_context = gather_data_context()
        cell = gather_cell_info()
        return {
            "target_gateway": self.cfg.OPENCLAW_WS_URL,
            "registered": bool((network_info.get("registration") or {}).get("registered")),
            "network": network_info,
            "data_context": data_context,
            "cell": cell,
            "sim": sim_info,
            "runtime": gather_runtime_info(self.cfg, self.state),
            "recommendations": build_recommendations(sim_info, network_info, data_context),
            "ts": wall_time_ms(),
        }
