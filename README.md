# Failure Review Loop

首次使用只需阅读 [quickstart.md](quickstart.md)。

## 运行模型

| 概念 | 职责 |
|---|---|
| 当前目录 | 保存 FRL 配置、运行数据和报告 |
| 分析目标 | 创建定时任务时输入；每个任务只保存一个目标 |
| 定时任务 | 保存目标和调度参数，默认每天 `22:00` |
| CLI | 按任务传入的目标筛选 Codex 本地会话并维护确定性状态 |
| 原生子代理 | 根据已采集证据生成 findings 或 proposal 契约 JSON |

目标路径不写入 `.sdd-frl/config.json`。任务运行时通过以下命令传入：

```powershell
sdd-frl prepare . --target "C:\work\product-a"
```

运行范围默认是配置时区中最近一个完整自然日。所有写入保留在当前目录；分析目标只读。

## 初始化产物

```text
当前目录/
├─ README.md
├─ quickstart.md
├─ .sdd-frl/
│  ├─ config.json
│  ├─ automation/task-prompt.md
│  ├─ contracts/
│  ├─ runs/
│  └─ locks/
├─ .codex/agents/
│  ├─ sdd-frl-analyst.toml
│  └─ sdd-frl-optimizer.toml
└─ docs/failure-review/<project_id>/
```

配置只保存时区、Codex 数据源位置和输出目录；本地回归固定采集原始内容。

## 运行状态机

```text
prepare → SPAWN_ANALYST → continue analyst
        → [SPAWN_OPTIMIZER → continue optimizer]
        → FINALIZE → finalize → STOP
```

`next_action` 是唯一阶段路由依据。Agent 输出先写入 handoff 指定路径，再由 CLI
执行 JSON Schema（JSON 结构约束）、运行身份和阶段顺序校验。

## 数据采集结果

| 情况 | 结果 |
|---|---|
| Codex session 数据源不可读 | `FAILED_COLLECTION / CODEX_SOURCE_UNAVAILABLE` |
| 没有找到属于本次目标的对话 | `FAILED_COLLECTION / TARGET_CONVERSATIONS_NOT_FOUND` |
| 目标对话存在，但窗口内无事件 | `COMPLETED_NO_TASKS / NO_EVENTS_IN_WINDOW` |
| 窗口内事件均不可采集 | `COMPLETED_NO_TASKS / EVENTS_IN_WINDOW_UNCOLLECTABLE` |

采集结果继续通过 `source-records.schema.json` 和 `evidence.schema.json` 校验。窗口采用
半开区间 `[start, end)`；窗口外只保存计数和布尔边界信息，不复制正文。

## 旧版本

本版本不迁移旧的持久目标配置。旧目录需要移除旧 `.sdd-frl/config.json` 后重新执行
干净的 `sdd-frl init .`；运行数据目录可以单独保留。
