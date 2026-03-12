# 快速开始（官方 OpenClaw，无需修改 Gateway 源码）

## 1. 前置条件

1. OpenClaw Gateway 已安装并运行。
2. 你具备设备可访问的 `ws://` 或 `wss://` 地址。
3. QuecPython 模组可在 `/usr` 下运行脚本。
4. 你已经知道目标 Gateway 采用哪条鉴权路径。
5. 如果你希望从 Gateway RPC / CLI 触发 `qpy.*` 命令，则目标 Gateway 需要允许这类命令到达该节点平台。

## 2. 选择鉴权路径

| 场景 | 必需配置 | 说明 |
|---|---|---|
| Gateway 接受 token 路径 | `OPENCLAW_AUTH_TOKEN` + `OPENCLAW_DEVICE_AUTH_MODE="none"` | 最简单的社区联调路径 |
| Gateway 强制官方设备身份 | `OPENCLAW_AUTH_TOKEN` + `OPENCLAW_DEVICE_AUTH_MODE="remote_signer_http"` | 需要额外启动 `tools/remote_signer_http.mjs` |

## 3. 准备设备端文件

1. 将 `usr_mirror/_main.py` 复制到设备 `/usr/_main.py`。
2. 将 `usr_mirror/app/*` 复制到设备 `/usr/app/`。
3. 编辑 `/usr/app/config.py`，填入你的 Gateway 地址、token 与逻辑 `DEVICE_ID`。
4. 保持默认 client 标识与上游对齐：

```python
OPENCLAW_CLIENT_ID = "node-host"
OPENCLAW_CLIENT_MODE = "node"
OPENCLAW_CLIENT_PLATFORM = "quectel"
OPENCLAW_CLIENT_DEVICE_FAMILY = "quecpython"
```

5. 内置运行时默认不会在 WebSocket 握手中发送浏览器 `Origin` 头。除非你的 Gateway 明确要求，否则不要自行添加。

## 3.1 可选：在 Gateway 放行 `qpy.*`

OpenClaw 对未知平台族采用保守放行策略。对 `quectel/quecpython`，如果你希望 Gateway 侧的 `node.invoke` 能真正下发到设备，需要把设备命令加入 `gateway.nodes.allowCommands`：

```json
{
  "gateway": {
    "nodes": {
      "allowCommands": [
        "qpy.device.info",
        "qpy.device.status",
        "qpy.net.diag",
        "qpy.sim.info",
        "qpy.cell.info",
        "qpy.runtime.status",
        "qpy.tools.catalog",
        "tool_device_info",
        "tool_net_diag"
      ]
    }
  }
}
```

## 4. 可选：启动 Remote Signer

如果你的 Gateway 强制官方设备身份鉴权，请在设备可访问的主机上启动仓库内置 signer helper：

```bash
REMOTE_SIGNER_PORT=8787 \
REMOTE_SIGNER_AUTH_TOKEN=replace_me \
node tools/remote_signer_http.mjs
```

然后在设备侧配置：

```python
OPENCLAW_DEVICE_AUTH_MODE = "remote_signer_http"
REMOTE_SIGNER_HTTP_URL = "http://<reachable-host>:8787/sign"
REMOTE_SIGNER_HTTP_AUTH_TOKEN = "replace_me"
```

补充说明：
1. 如果未显式设置 `REMOTE_SIGNER_IDENTITY_DIR`，signer 会把生成的身份文件保存在主机用户目录下的 `~/.lcc-claw-node-qpy/remote-signer/identities/`，而不是仓库目录。
2. 这意味着仓库默认不会产生可误提交的本地私钥状态文件。

## 5. 启动运行时

设备端执行：

```python
import _main
```

## 6. 验证连接

启动后，预期行为如下：

1. 设备收到 `connect.challenge`。
2. 设备发送 `connect`。
3. 如果设备是首次接入，Gateway 可能先返回 `pairing required`。
4. 在 Gateway 侧批准待配对设备，例如：

```bash
openclaw devices approve --latest
```

5. 运行时进入在线循环并开始 `heartbeat`。
6. Gateway 可以下发 `node.invoke.request`。
7. 设备返回 `node.invoke.result`。

建议优先验证以下命令：

1. `qpy.tools.catalog`
2. `qpy.runtime.status`
3. `qpy.device.status`
4. `qpy.net.diag`
5. `qpy.sim.info`
6. `qpy.cell.info`
7. `qpy.device.info`

## 7. 使用 Mock Gateway 做本地开发验证

使用仓库内置 mock server 做本地握手和 `invoke` smoke：

```bash
python tests/mock_gateway/mock_gateway.py \
  --host 127.0.0.1 \
  --port 18789 \
  --invoke-command qpy.runtime.status
```

mock server 会：

1. 完成 WebSocket 升级。
2. 发送 `connect.challenge`。
3. 接受 `connect`。
4. 按参数发送一条 `node.invoke.request`。
5. 打印设备侧 `node.event` 与 `node.invoke.result` 帧。
