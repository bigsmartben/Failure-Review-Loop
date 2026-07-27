# 定时任务配置

## 工作区模型

每个定时任务绑定一个目标项目，并在该项目根目录执行 `sdd-frl run .`。

```text
项目 A 的定时任务 ──▶ 项目 A/.sdd-frl + 项目 A/docs/failure-review
项目 B 的定时任务 ──▶ 项目 B/.sdd-frl + 项目 B/docs/failure-review
```

项目之间没有共享运行目录，也不再依赖中央 `Failure-Review-Loop` 运行器。

## 创建步骤

用户只有三步操作：

1. 使用 `uv tool install` 从 Git 标签安装 `sdd-frl`。
2. 在目标项目运行 `sdd-frl init .`。
3. 打开根目录 `quickstart.md`，复制唯一代码框，粘贴到 Codex App 当前项目的对话并发送。

代码框只要求 Codex 读取 `.sdd-frl/automation/task-prompt.md` 并创建任务。用户不需要
打开隐藏文件，也不需要手工执行 `probe`、`run` 或设置周期、时区和任务描述。
生成的提示词包含目标工作区绝对路径、项目 ID、配置时区和每天 09:00 的频率。
定时任务内部执行 `sdd-frl run .`，默认复盘配置时区内最近一个完整自然日。

## 写入边界

| 内容 | 位置 |
|---|---|
| 配置和任务提示词 | `.sdd-frl/` |
| 原始证据、指标和日志 | `.sdd-frl/runs/<run_id>/` |
| 活动锁 | `.sdd-frl/locks/` |
| 最终文档 | `docs/failure-review/YYYY-MM-DD.md` |

允许从 Codex 全局会话目录只读采集；所有写操作必须留在目标工作区。
