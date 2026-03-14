# Device runtime configuration.
# Keep values generic in OSS repo. Do not commit real secrets.

DEVICE_ID = "dev_demo_001"
DEVICE_NAME = "QuecPython Demo Node"
TENANT_ID = "tenant_demo"

ACCESS_MODE = "ws_native"

OPENCLAW_WS_URL = "ws://127.0.0.1:18789"
OPENCLAW_ROLE = "node"
OPENCLAW_MIN_PROTOCOL = 3
OPENCLAW_MAX_PROTOCOL = 3
OPENCLAW_CLIENT_ID = "node-host"
OPENCLAW_CLIENT_MODE = "node"
OPENCLAW_CLIENT_PLATFORM = "quectel"
OPENCLAW_CLIENT_DEVICE_FAMILY = "quecpython"
OPENCLAW_CLIENT_DISPLAY_NAME = "QuecPython OpenClaw Node"
OPENCLAW_USER_AGENT = "lcc-claw-node-qpy/1.0.0"

OPENCLAW_AUTH_TOKEN = "replace_with_your_token"
OPENCLAW_DEVICE_AUTH_MODE = "none"
REMOTE_SIGNER_HTTP_URL = ""
REMOTE_SIGNER_HTTP_AUTH_TOKEN = ""
REMOTE_SIGNER_HTTP_TIMEOUT_SEC = 5
REMOTE_SIGNER_HTTP_HEADERS = {}

# Stock official Gateway does not consume custom heartbeat/telemetry/lifecycle/alert
# node.event names by default. Keep raw generic node events disabled unless your
# Gateway extension explicitly handles them.
OPENCLAW_GENERIC_NODE_EVENTS = False

# Stock-Gateway-compatible proactive uplink path. Default business alerts use
# node.event(event="agent.request") so the official Gateway can consume them
# without source changes.
OPENCLAW_ALERT_UPLINK_MODE = "agent_request"
OPENCLAW_AGENT_REQUEST_SESSION_KEY = ""
OPENCLAW_AGENT_REQUEST_DELIVER = False
OPENCLAW_AGENT_REQUEST_CHANNEL = ""
OPENCLAW_AGENT_REQUEST_TO = ""
OPENCLAW_AGENT_REQUEST_RECEIPT = False
OPENCLAW_AGENT_REQUEST_RECEIPT_TEXT = "Device alert received."
OPENCLAW_AGENT_REQUEST_THINKING = "low"
OPENCLAW_AGENT_REQUEST_TIMEOUT_SECONDS = 0

HEARTBEAT_INTERVAL_SEC = 15
TELEMETRY_INTERVAL_SEC = 60
RECONNECT_BACKOFF_SEC = 5
CONNECT_TIMEOUT_SEC = 8
ACK_TIMEOUT_MS = 5000
READ_POLL_MS = 200
MAX_CMD_EXEC_SEC = 10
OUTBOX_MAX = 64
DEDUPE_WINDOW = 64
MAX_RETRY = 3
OUTBOX_RETRY_BACKOFF_MS = 1000
SENSITIVE_MASK = True

OPENCLAW_CAPS = [
    "diagnostics",
    "network",
    "telemetry",
]

OPENCLAW_COMMANDS = [
    "qpy.device.info",
    "qpy.device.status",
    "qpy.net.diag",
    "qpy.sim.info",
    "qpy.cell.info",
    "qpy.runtime.status",
    "qpy.tools.catalog",
    "tool_device_info",
    "tool_net_diag",
]

ALLOW_TOOLS = OPENCLAW_COMMANDS
OPENCLAW_SCOPES = []
OPENCLAW_PERMISSIONS = {}

SAFE_MODE = False
SAFE_MODE_FAILURE_THRESHOLD = 6
SAFE_MODE_COOLDOWN_SEC = 30
FW_VERSION = "v1.0.0"
