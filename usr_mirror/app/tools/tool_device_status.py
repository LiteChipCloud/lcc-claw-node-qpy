from app.tools.tool_probe import build_device_status


class ToolDeviceStatus(object):

    def __init__(self, cfg, state):
        self.cfg = cfg
        self.state = state

    def execute(self, args):
        mask_sensitive = bool(args.get("mask_sensitive", getattr(self.cfg, "SENSITIVE_MASK", True))) if args else bool(getattr(self.cfg, "SENSITIVE_MASK", True))
        return build_device_status(self.cfg, self.state, mask_sensitive)
