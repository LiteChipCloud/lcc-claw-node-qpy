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

## 3.1 部署策略建议

如果你通过 Windows/Host 工具向设备推送运行时文件，建议先按以下原则执行：

| 场景 | 推荐动作 | 原因 |
|---|---|---|
| 首次安装 | 全量部署 `usr_mirror` | 设备还没有运行时基线 |
| 日常联调 | 仅增量推送变更文件 | 大文件整包 REPL 下发更容易失败 |
| 配置变更 | 显式覆盖 `/usr/app/config.py` | 避免示例配置误覆盖 live config |
| 仅恢复在线 | 不改文件，只重启 `/usr/_main.py` | 降低二次破坏风险 |

补充说明：
1. 开源仓库中的示例 `config.py` 应视为模板，不应在未知现场环境中自动覆盖 live config。
2. 高频调试不要把“整包覆盖 + 自动启动”当成唯一入口。
3. 更详细的部署与恢复规则见 [docs/design/07-Windows部署与现场运维设计.md](design/07-Windows部署与现场运维设计.md)。

Windows / Host 侧推荐命令：

```bash
# Mac -> Windows：先安装常驻 toolkit
./scripts/windows_qpyctl.sh install

# 只同步并下发当前修改的运行时代码
./scripts/windows_qpyctl.sh deploy --file app/command_worker.py --file app/runtime_state.py

# 大文件给更高 timeout 预算
./scripts/windows_qpyctl.sh deploy --file app/tools/tool_probe.py --timeout 120

# 启动与快照走固定入口
./scripts/windows_qpyctl.sh start
./scripts/windows_qpyctl.sh snapshot

# 历史 tmp 残留先做报告，不默认删除
./scripts/windows_qpyctl.sh cleanup-tmp --json
```

如果你想理解为什么这个入口能减少重复传输，见 [docs/design/08-Windows常驻Toolkit与SSH执行模型.md](design/08-Windows常驻Toolkit与SSH执行模型.md)。

```powershell
# 首次安装或全量同步
$env:QPY_PUSH_CONFIG = 'auto'
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_to_device.ps1

# 日常增量部署
$env:QPY_FILES = 'app/command_worker.py,app/runtime_state.py'
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_to_device.ps1

# 显式配置覆盖
$env:QPY_PUSH_CONFIG = 'override'
$env:QPY_CONFIG_FILE = 'C:\path\to\live-config.py'
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_to_device.ps1

# 自动探测 REPL 口
$env:QPY_AUTO_PORT = '1'
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_to_device.ps1

# 启动与快照分离
powershell -ExecutionPolicy Bypass -File .\scripts\start_runtime.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\debug_snapshot.ps1
```

## 3.2 可选：在 Gateway 放行 `qpy.*`

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

如果你是通过 Windows / Host 工具部署，建议把验证分成两个阶段：

1. 部署后先执行 `scripts/debug_snapshot.ps1`，确认运行时状态和设备配置没有被误覆盖。
2. 再从 Gateway 侧发起 `qpy.tools.catalog` 和 `qpy.runtime.status`。

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
