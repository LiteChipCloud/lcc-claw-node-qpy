import utime


class ToolDeviceInfo(object):

    def __init__(self, cfg):
        self.cfg = cfg

    def execute(self, args):
        _ = args
        return {
            "device_id": self.cfg.DEVICE_ID,
            "tenant_id": self.cfg.TENANT_ID,
            "fw_version": self.cfg.FW_VERSION,
            "access_mode": self.cfg.ACCESS_MODE,
            "ts": utime.ticks_ms(),
        }
