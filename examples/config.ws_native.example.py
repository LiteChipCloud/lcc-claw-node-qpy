# Example config for ws_native mode.
# Copy values into /usr/app/config.py on device.

DEVICE_ID = "dev_your_id"
TENANT_ID = "tenant_your_id"
ACCESS_MODE = "ws_native"

OPENCLAW_WS_URL = "ws://<gateway-host>:18789"
OPENCLAW_AUTH_TOKEN = "<token>"

HEARTBEAT_INTERVAL_SEC = 15
RECONNECT_BACKOFF_SEC = 5
MAX_CMD_EXEC_SEC = 10

ALLOW_TOOLS = [
    "tool_device_info",
    "tool_net_diag",
]

SAFE_MODE = False
FW_VERSION = "v0.1.0"
