# 定时任务契约

用户只执行安装、`sdd-frl init .` 和 quickstart 第三步。

每次第三步消息只能包含一个分析目标。Codex 为它创建一个独立定时任务；每增加一个
目标，就重新发送一次第三步消息。各任务分别保存自己的目标、运行频率和运行时间，
互不影响。

| 参数 | 规则 |
|---|---|
| 分析目标 | 必填；只能来自用户当前消息 |
| 运行频率 | 可选，默认每天 |
| 运行时间 | 可选，默认 `22:00` |
| 当前目录 | 内部固定，不询问、不展示 |

任务运行时执行：

```text
prepare --target <目标> → SPAWN_ANALYST → continue analyst
                        → [SPAWN_OPTIMIZER → continue optimizer]
                        → FINALIZE → finalize → STOP
```

目标路径只进入对应任务及该任务产生的 `run.json`，不会写入
`.sdd-frl/config.json`。CLI 根据目标路径筛选 Codex 本地会话；数据源不可读或没有
找到目标对话时，本次运行失败。所有运行产物和报告写入当前目录，目标目录保持只读。
