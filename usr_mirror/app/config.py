# Device runtime configuration.
# Keep values generic in OSS repo. Do not commit real secrets.

DEVICE_ID = "dev_demo_001"
TENANT_ID = "tenant_demo"

ACCESS_MODE = "ws_native"

OPENCLAW_WS_URL = "ws://127.0.0.1:18789"
OPENCLAW_AUTH_TOKEN = "replace_with_your_token"

HEARTBEAT_INTERVAL_SEC = 15
RECONNECT_BACKOFF_SEC = 5
MAX_CMD_EXEC_SEC = 10

ALLOW_TOOLS = [
    "tool_device_info",
    "tool_net_diag",
]

SAFE_MODE = False
FW_VERSION = "v0.1.0"
