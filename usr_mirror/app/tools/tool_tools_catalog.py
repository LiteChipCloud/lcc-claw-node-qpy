from app.tools.tool_probe import build_tool_catalog, wall_time_ms


class ToolToolsCatalog(object):

    def __init__(self, cfg, state, catalog_provider):
        self.cfg = cfg
        self.state = state
        self.catalog_provider = catalog_provider

    def execute(self, args):
        _ = args
        catalog = build_tool_catalog(self.catalog_provider())
        return {
            "node_id": self.state.node_id,
            "tool_count": len(catalog),
            "tools": catalog,
            "ts": wall_time_ms(),
        }
