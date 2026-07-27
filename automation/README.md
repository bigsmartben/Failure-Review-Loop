# 定时任务配置

## 工作区模型

每个定时任务绑定一个执行过 `sdd-frl init` 的 FRL 工作区和另一个 Codex
项目目录作为分析目标。Codex App 是
scheduler（调度器）和 native subagent orchestrator（原生子代理编排器）；
CLI 只负责确定性状态与校验。

```text
FRL 工作区 ──只读采集──▶ 项目 A 的 Codex App 对话
       │
       └──写入──▶ .sdd-frl + docs/failure-review
```

分析目标中不安装 FRL，也不写入运行产物。

## 创建步骤

用户只有三步操作：

1. 使用 `uv tool install` 从 Git 标签安装 `sdd-frl`。
2. 在 FRL 工作区执行 `sdd-frl init . --analysis-target <PATH>`。
3. 打开 FRL 工作区根目录 `quickstart.md`，复制唯一代码框，粘贴到该工作区的
   Codex App 对话并发送。

代码框只要求 Codex 读取 `.sdd-frl/automation/task-prompt.md` 并创建任务。用户不需要
打开隐藏文件，也不需要手工执行 `probe`、`run` 或设置周期、时区和任务描述。
生成的提示词包含 FRL 工作区、分析目标、项目 ID、配置时区和每天 09:00 的频率。
定时任务内部执行以下闭环，默认复盘配置时区内最近一个完整自然日：

```text
prepare → SPAWN_ANALYST → continue analyst
        → [SPAWN_OPTIMIZER → continue optimizer]
        → FINALIZE → finalize → STOP
```

`next_action` 是唯一阶段路由依据。Agent 输出必须先写入 handoff 指定路径，再由
CLI 执行 Schema、运行身份和阶段顺序校验。

任务创建前的 `probe` 同时检查 Codex session 根是否可访问，以及现有样本能否绑定
分析目标。运行时，数据源不可用或目标绑定为空都会返回 blocker；只有目标对话已
匹配而指定窗口内无记录时，才报告 `COMPLETED_NO_TASKS`。

## 写入边界

| 内容 | 位置 |
|---|---|
| 配置和任务提示词 | `.sdd-frl/` |
| 原生 Agent 配置 | `.codex/agents/sdd-frl-*.toml` |
| 运行期 Prompt 与 Schema 副本 | `.sdd-frl/contracts/` |
| 原始证据、指标和日志 | `.sdd-frl/runs/<run_id>/` |
| 活动锁 | `.sdd-frl/locks/` |
| 最终文档 | `docs/failure-review/YYYY-MM-DD.md` |

允许从 Codex 全局会话目录和分析目标只读采集；所有写操作必须留在 FRL 工作区。
