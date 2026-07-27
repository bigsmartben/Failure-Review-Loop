# Failure Review Loop 维护说明

本文面向维护者（maintainer）：负责安装、检查和排查 Failure Review Loop 的人。

如果你只是第一次设置，请不要读这份维护说明，直接打开
[quickstart.md](quickstart.md)。

## 运行契约

| 项目 | 约定 |
|---|---|
| 复盘对象 | 定时任务绑定的当前项目 |
| 执行时间 | 每天 09:00，使用项目配置的时区 |
| 执行命令 | `sdd-frl run .` |
| 时间范围 | 最近一个完整自然日 |
| 最终报告 | `docs/failure-review/YYYY-MM-DD.md` |
| 运行记录 | `.sdd-frl/runs/<run_id>/` |

例如，时区为 `Asia/Shanghai`，任务在 2026-07-27 09:00 执行时，复盘范围是
2026-07-26 00:00 至 2026-07-27 00:00。

## 初始化后的目录

```text
目标项目/
├─ README.md
├─ quickstart.md
├─ failure-review.project.json
├─ .sdd-frl/
│  ├─ config.json
│  ├─ automation/task-prompt.md
│  ├─ runs/
│  └─ locks/
└─ docs/failure-review/
```

| 路径 | 维护用途 |
|---|---|
| `failure-review.project.json` | 确认项目身份 |
| `.sdd-frl/config.json` | 确认项目、时区、模型和输出位置 |
| `.sdd-frl/automation/task-prompt.md` | 创建定时任务的权威提示词 |
| `.sdd-frl/runs/` | 查看证据、指标和失败日志 |
| `docs/failure-review/` | 查看给人阅读的最终报告 |

## 验收

初始化后执行：

```powershell
sdd-frl probe .
```

返回结果中的 `workspace`、`project_id` 和 `timezone` 必须与目标项目一致。

创建定时任务后，还要确认：

| 检查项 | 正确结果 |
|---|---|
| 任务名称 | `sdd-frl · <project_id>` |
| 工作区 | 目标项目的绝对路径 |
| 频率 | 每天 09:00 |
| 状态 | 已启用 |

## 手工复盘

通常不需要手工运行。排查问题时可以指定日期：

```powershell
sdd-frl run . --date 2026-07-26
```

成功时返回 `run_id`、状态和报告绝对路径。

## 失败处理

| 错误或状态 | 处理 |
|---|---|
| `WORKSPACE_NOT_INITIALIZED` | 在目标项目执行 `sdd-frl init .` |
| `TIMEZONE_REQUIRED` | 执行 `sdd-frl init . --timezone Asia/Shanghai` |
| `WORKSPACE_PROJECT_MISMATCH` | 检查 marker 与 `.sdd-frl/config.json` 的项目 ID |
| `OVERLAPPING_RUN` | 等待当前运行结束，不要并行启动第二次 |
| `SETUP_BLOCKED` | 按 Codex 返回的具体原因处理后，重新执行 quickstart 第三步 |
| `FAILED_*` | 查看 `.sdd-frl/runs/<run_id>/report.md` |

失败运行不会覆盖同一天已有的成功报告。

## 写入边界

- Codex 会话目录只读。
- 配置、锁、运行记录和报告只能写入当前项目。
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
