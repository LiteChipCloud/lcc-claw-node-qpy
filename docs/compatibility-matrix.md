# Compatibility Matrix

## Runtime Matrix

| Item | Policy | Notes |
|---|---|---|
| QuecPython runtime files | Supported | `/usr` 运行时为交付核心 |
| OpenClaw upstream unmodified gateway | Target baseline | 首版以“零改 Gateway”作为设计基线 |
| Third-party self-hosted official Gateway | Supported by design | 前提是协议兼容、网络可达、鉴权满足 |
| Customized Gateway with changed protocol/auth flow | Not guaranteed | 超出 OSS 首版兼容承诺 |
| `ws_native` connect/reconnect | Implemented | 已实现 challenge/connect/heartbeat/reconnect 主链路 |
| Full WS text-frame protocol | Implemented for OSS v1.0 baseline | 覆盖 connect、event、response、invoke/result 与 ACK |
| `node.invoke.request/result` bidirectional loop | Implemented | 可执行工具并回传结构化结果 |
| `node.event` proactive reporting | Implemented | heartbeat/telemetry/lifecycle 已内置，alert 复用同一通道 |
| `remote_signer_http` | Implemented | 面向强制设备签名 Gateway 的可选补充路径 |
| Official Gateway node handshake constraints | Validated | 设备侧默认使用 `client.id=node-host`，且不发送浏览器 `Origin` 头 |
| First-time device pairing | Required by upstream | 首次接入返回 `NOT_PAIRED` 属于正常门禁，需要在 Gateway 批准 |
| `qpy.*` invoke on unknown platform family | Conditionally supported | 目标 Gateway 需将 `qpy.*`/别名加入 `gateway.nodes.allowCommands` |
| `mqtt_fleet` | Out of v1.0 scope | 企业版路线，不纳入 OSS 首版 |

## Authentication Matrix

| Scenario | Policy | Notes |
|---|---|---|
| Gateway accepts token-based auth | Preferred OSS path | 社区用户最容易复现 |
| Gateway requires device signature and device can sign locally | Supported by design | 设备侧自行满足安全要求 |
| Gateway requires device signature and device cannot sign locally | Conditionally supported | 需要外置 signer；仍不要求改 Gateway |
| Gateway requires private enterprise auth plugin | Not covered | 不属于 OSS 基线 |

## OpenClaw Version Policy

| OpenClaw line | Policy | Notes |
|---|---|---|
| stable | Mandatory smoke check before release | 开源发布门禁 |
| latest | Best-effort smoke check | 用于前瞻兼容检查 |

## Device Model Policy

- Officially supported models are published per release tag.
- Unsupported models may work but are not covered by SLA.
- When a model lacks required crypto/network capability, users may need a compatible external signer or custom validation.
- `quectel/quecpython` 这类未进入 OpenClaw 默认平台映射的设备，若要从 Gateway 触发 `qpy.*` 命令，需要补充 `gateway.nodes.allowCommands`。
