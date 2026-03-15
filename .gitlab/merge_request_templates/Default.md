## 1. 变更摘要

### Why
<!-- 一句话说明为什么做这次改动 -->

### Scope
<!-- 一句话说明这次 MR 的唯一目标，不要写多个不相关目标 -->

## 2. Repo-Lane 身份

| 字段 | 值 |
| --- | --- |
| target_repo | lcc-claw-node-qpy |
| business_thread_id |  |
| repo_lane |  |
| branch |  |
| stack_parent | none / !<iid> |
| risk_class | fast-track / standard / high-risk |
| change_type | code / docs / release / config / ops |

## 3. 追踪信息

| 系统 | 链接/编号 |
| --- | --- |
| OpenProject | WP# |
| GitLab Issue | # |
| Docmost | page_id |

## 4. 风险与边界

- 是否涉及 runtime / transport / deployment：是 / 否
- 是否涉及 validation evidence / release assets：是 / 否
- 是否与其他 opened MR 存在覆盖或替代关系：是 / 否
- freeze_scope（不得触碰区域）：
  -

## 5. 测试与证据

### Automated
<!-- 执行过的命令和结果摘要 -->

### Manual
<!-- 手动验证、设备验证、回归摘要 -->

### Evidence
<!-- 报告、截图、日志、发布物摘要 -->

## 6. Merge Readiness Checklist

- [ ] MR 从 Draft 启动，字段已补齐后才转 Ready
- [ ] 无无关混写 / 无错误 base / 无未声明 stack 关系
- [ ] 已完成自测，并提供 test evidence
- [ ] 若覆盖其他 opened MR，已明确 superseded 关系
- [ ] 无硬编码敏感信息
- [ ] 已更新必要文档或明确说明无需更新
- [ ] 知道新 commit 会使旧批准失效

## 7. Reviewer Notes
<!-- 需要 reviewer 特别关注的点 -->
