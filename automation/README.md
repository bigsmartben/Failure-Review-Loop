# 定时任务配置

## 工作区模型

每个定时任务绑定一个目标项目，并在该项目根目录执行 `sdd-frl run .`。

```text
项目 A 的定时任务 ──▶ 项目 A/.sdd-frl + 项目 A/docs/failure-review
项目 B 的定时任务 ──▶ 项目 B/.sdd-frl + 项目 B/docs/failure-review
```

项目之间没有共享运行目录，也不再依赖中央 `Failure-Review-Loop` 运行器。

## 创建步骤

1. 安装 `sdd-frl`。
2. 在目标项目运行 `sdd-frl init .`。
3. 手工运行一次 `sdd-frl probe .` 和 `sdd-frl run . --date YYYY-MM-DD`。
4. 在 Codex 桌面端创建定时任务，把项目设为该目标项目。
5. 将 `.sdd-frl/automation/task-prompt.md` 全文粘贴到任务描述。
6. 设置周期、时区和通知。

CLI 默认复盘配置时区内最近一个完整自然日，因此每天运行一次时无需由模型计算窗口。

## 写入边界

| 内容 | 位置 |
|---|---|
| 配置和任务提示词 | `.sdd-frl/` |
| 原始证据、指标和日志 | `.sdd-frl/runs/<run_id>/` |
| 活动锁 | `.sdd-frl/locks/` |
| 最终文档 | `docs/failure-review/YYYY-MM-DD.md` |

允许从 Codex 全局会话目录只读采集；所有写操作必须留在目标工作区。
