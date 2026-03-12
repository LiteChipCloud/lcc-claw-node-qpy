# Release Assets 说明

> 适用版本：`v1.0.0-rc1`

## 1. 目标

本文件定义 GitHub draft prerelease 需要附带的离线资产，避免用户只能通过源码仓库手工拼装设备端运行环境。

## 2. 资产清单

| 资产名模式 | 内容 | 用途 |
|---|---|---|
| `lcc-claw-node-qpy-<version>-runtime.zip` | `usr_mirror/` | 设备端运行时主包，直接部署到 `/usr` |
| `lcc-claw-node-qpy-<version>-examples.zip` | `examples/` | 示例配置包，方便用户快速生成设备配置 |
| `lcc-claw-node-qpy-<version>-docs.zip` | `README.md + docs/` | 离线文档包，便于现场部署和离线阅读 |
| `SHA256SUMS.txt` | 校验摘要 | 下载后校验资产完整性 |

## 3. 生成方式

使用仓库脚本：

```bash
./scripts/build_release_assets.sh v1.0.0-rc1
```

默认输出目录：

```text
dist/release-assets/v1.0.0-rc1/
```

## 4. 上传建议

建议将以上四个文件上传到 GitHub draft prerelease：

1. 运行时主包
2. 示例配置包
3. 离线文档包
4. `SHA256SUMS.txt`

## 5. 说明

1. 生成资产前应先通过 `python3 tools/sanitize_check.py --root .`
2. 不要把 `dist/` 目录提交进仓库
3. draft prerelease 可先附带资产，待 `72h soak` 通过后再决定是否正式发布稳定版
