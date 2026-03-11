import utime


class ToolNetDiag(object):

    def __init__(self, cfg):
        self.cfg = cfg

    def execute(self, args):
        target = args.get("target") if args else None
        if not target:
            target = self.cfg.OPENCLAW_WS_URL
        return {
            "target": target,
            "status": "reachable_check_not_implemented_in_rc0",
            "ts": utime.ticks_ms(),
        }
