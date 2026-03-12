from app.tools.tool_probe import gather_cell_info, gather_network_info, wall_time_ms


class ToolCellInfo(object):

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state

    def execute(self, args):
        _ = args
        network = gather_network_info()
        return {
            "node_id": self.state.node_id,
            "cell": gather_cell_info(),
            "operator": network.get("operator"),
            "signal": network.get("signal"),
            "ts": wall_time_ms(),
        }
