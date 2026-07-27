# 隐私、保留与版本控制策略

| 项目 | 策略 |
|---|---|
| 原始对话 | 不整份复制；只保存窗口内、目标项目内的相关事件 |
| 窗口边界 | 只保存窗口外是否存在事件的布尔标记，不复制窗口外内容 |
| 项目归属 | 显式 conversation ID 优先；否则规范化 `session_meta.cwd` 并检查其位于分析目标内 |
| 改进载体 | 每个项目只读取 `project_bindings[].improvement_target_ids` 绑定的文件 |
| 敏感信息 | 默认按常见 token、密钥和密码模式脱敏 |
| 指标与趋势 | 只保存任务计数、分布和比率，不复制新的对话内容 |
| Git | `runs/*` 默认忽略，只保留 `.gitkeep` |
| 保留期限 | `retention_days: null` 表示不自动删除 |
| 自动清理 | 不执行破坏性清理 |

Codex App `projectId` 可以为空，也不作为身份门。例：session 的 `cwd` 为
`C:\work\harness\nested`，分析目标为 `C:\work\harness`，即使 `projectId: null`
仍会采集；FRL 工作区自身的 session 会计入 `skipped_outside_target`。

窗口外只保存计数和每个目标对话的前后事件布尔值，不保存窗口外正文。

多项目配置必须为每个项目显式绑定 `improvement_target_ids`，防止一次运行读取其他项目的 Skill、AGENTS.md、提示词、脚本或模板。

正则脱敏不能保证识别所有业务敏感信息。首次接入新项目时，应抽查 `source-records.json`，必要时增加项目专用规则。
