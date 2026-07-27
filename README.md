# Failure Review Loop 维护说明

本文面向维护者（maintainer）：负责安装、检查和排查 Failure Review Loop 的人。

如果你只是第一次设置，请不要读这份维护说明，直接打开
[quickstart.md](quickstart.md)。

## 运行契约

| 项目 | 约定 |
|---|---|
| FRL 工作区（FRL workspace） | 执行 `sdd-frl init` 的目录；保存配置、运行产物和报告 |
| 分析目标（analysis target） | 另一个 Codex 项目目录；按会话 `cwd` 只读采集 Codex App 对话 |
| 执行时间 | 每天 09:00，使用项目配置的时区 |
| 运行宿主 | Codex App Scheduled Task（定时任务） |
| CLI 状态机 | `prepare → continue → finalize` |
| 子代理 | `sdd_frl_analyst`、`sdd_frl_optimizer` |
| 时间范围 | 最近一个完整自然日 |
| 最终报告 | `docs/failure-review/YYYY-MM-DD.md` |
| 运行记录 | `.sdd-frl/runs/<run_id>/` |

例如，时区为 `Asia/Shanghai`，任务在 2026-07-27 09:00 执行时，复盘范围是
2026-07-26 00:00 至 2026-07-27 00:00。

```text
FRL 工作区 ──只读采集 Codex App 会话──▶ 分析目标
       │
       └──写入──▶ .sdd-frl/runs + docs/failure-review
```

## 初始化后的目录

```text
FRL 工作区/
├─ README.md
├─ quickstart.md
├─ failure-review.project.json
├─ .sdd-frl/
│  ├─ config.json
│  ├─ automation/task-prompt.md
│  ├─ contracts/
│  ├─ runs/
│  └─ locks/
├─ .codex/agents/
│  ├─ sdd-frl-analyst.toml
│  └─ sdd-frl-optimizer.toml
└─ docs/failure-review/
```

| 路径 | 维护用途 |
|---|---|
| `failure-review.project.json` | 确认 FRL 工作区身份 |
| `.sdd-frl/config.json` | 确认运行器、分析目标、时区和输出位置；不保存模型配置 |
| `.sdd-frl/automation/task-prompt.md` | 创建定时任务的权威提示词 |
| `.codex/agents/*.toml` | 模型、推理强度、只读沙箱和角色职责 |
| `.sdd-frl/contracts/` | 原生子代理读取的 Prompt、Schema 与去重契约 |
| `.sdd-frl/runs/` | 查看证据、指标和失败日志 |
| `docs/failure-review/` | 查看给人阅读的最终报告 |

## 验收

初始化后执行：

```powershell
sdd-frl probe .
```

返回结果中的 `workspace`、`analysis_target`、`project_id` 和 `timezone`
必须分别与 FRL 工作区和被复盘项目一致。`source.available` 必须为 `true`；
`source.target_binding_verified` 表示当前 session 样本中是否已找到目标对话，
不是依赖 Codex App `projectId`。

创建定时任务后，还要确认：

| 检查项 | 正确结果 |
|---|---|
| 任务名称 | `sdd-frl · <project_id>` |
| FRL 工作区 | 执行 `sdd-frl init` 的目录绝对路径 |
| 分析目标 | 被复盘 Codex 项目的绝对路径 |
| 频率 | 每天 09:00 |
| 状态 | 已启用 |

## 手工复盘

通常不需要手工运行。排查状态机时可以指定日期：

```powershell
sdd-frl prepare . --date 2026-07-26
```

命令返回 handoff JSON。必须严格执行其 `next_action`；到达 `FINALIZE` 后运行：

```powershell
sdd-frl finalize . --run-id <run_id>
```

## 失败处理

| 错误或状态 | 处理 |
|---|---|
| `WORKSPACE_NOT_INITIALIZED` | 在 FRL 工作区执行 `sdd-frl init . --analysis-target <PATH>` |
| `TIMEZONE_REQUIRED` | 在 FRL 工作区执行 `sdd-frl init . --analysis-target <PATH> --timezone Asia/Shanghai` |
| `WORKSPACE_PROJECT_MISMATCH` | 检查 marker 与 `.sdd-frl/config.json` 的项目 ID |
| `ANALYSIS_TARGET_INVALID` | 修复 `.sdd-frl/config.json` 中的 `analysis_target` |
| `ANALYSIS_TARGET_REQUIRED` | 使用 `--analysis-target` 绑定另一个 Codex 项目目录 |
| `ANALYSIS_TARGET_NOT_DIRECTORY` | 恢复目标目录或重新绑定正确路径 |
| `ANALYSIS_TARGET_MUST_DIFFER` | 分析目标不能与 FRL 工作区是同一目录 |
| `ANALYSIS_TARGET_PATH_ESCAPE` | 将改进载体路径限制在分析目标内 |
| `CODEX_SOURCE_UNAVAILABLE` | 恢复或修正只读 Codex session 根；不得当作零任务成功 |
| `ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND` | 检查目标路径或显式 conversation ID；不得声称项目没有历史数据 |
| `AGENT_CONFIG_UNAVAILABLE` | 重新执行 `sdd-frl init .` 并在可信项目中打开新对话 |
| `AGENTS_DISABLED` | 移除项目配置中禁用原生子代理的设置 |
| `STAGE_ORDER_INVALID` | 按上一条 handoff 的 `next_action` 继续，不跳阶段 |
| `RUN_IDENTITY_MISMATCH` | 丢弃错误 Agent 输出，不跨运行复用 |
| `AGENT_OUTPUT_INVALID` | 查看 Agent 输出并按对应 Schema 修复 |
| `OVERLAPPING_RUN` | 等待当前运行结束，不要并行启动第二次 |
| `SETUP_BLOCKED` | 按 Codex 返回的具体原因处理后，重新执行 quickstart 第三步 |
| `FAILED_*` | 查看 `.sdd-frl/runs/<run_id>/report.md` |

失败运行不会覆盖同一天已有的成功报告。

`source-records.json` 保存 `collection_summary`（采集摘要）和 `empty_reason`
（空结果原因）。只有已经匹配目标对话、但半开窗口 `[start, end)` 内没有可采集
记录时，运行才可进入 `COMPLETED_NO_TASKS`。报告会同时显示窗口前、窗口内和窗口后
计数，但不复制窗口外对话正文。

## 写入边界

- Codex 会话目录只读。
- 分析目标只读；FRL 不在目标项目中安装配置或写报告。
- 配置、锁、运行记录和报告只能写入 FRL 工作区。
- Analyst 与 Optimizer 使用项目级只读 Agent TOML；Python 不再启动嵌套
  `codex exec`。
- Optimizer 只生成提案，不自动修改、提交、发布或部署文件。
- 已有 `README.md` 或 `quickstart.md` 不会被初始化器覆盖。

## 本仓库开发

CLI 契约（contract）和数据规则：

- [docs/uv-cli.md](docs/uv-cli.md)
- [docs/contracts/precedence.md](docs/contracts/precedence.md)
- [docs/privacy.md](docs/privacy.md)

运行测试：

```powershell
uv run pytest
npm test
```
