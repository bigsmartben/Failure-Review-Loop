# Failure Review Loop 当前设计

## 用户入口

用户只执行：

1. 安装 `sdd-frl`；
2. 在当前目录执行 `sdd-frl init .`；
3. 为一个分析目标创建一个独立定时任务。

调度参数默认每天 `22:00`。当前目录固定为内部运行和输出位置，不进入用户确认内容。

## 运行边界

- `.sdd-frl/config.json` 不保存任务目标。
- 每个任务通过 `prepare --target <绝对路径>` 传入唯一目标。
- 目标路径记录在该次 `run.json`，供同一运行的后续阶段校验。
- Collector 只接受 `session_meta.cwd` 位于本次目标内的 Codex 会话。
- 当前目录可写，目标目录只读。
- 本地回归数据按原始内容采集。

## 确定性契约

- `source-records.schema.json` 约束采集摘要、会话和原始记录。
- `evidence.schema.json` 约束规范化证据。
- `findings.schema.json` 和 `proposal.schema.json` 约束原生子代理输出。
- `prepare → continue → finalize` 负责阶段顺序、运行身份和失败语义。
- source/evidence 回归样例必须持续通过 Python 与 Node 契约测试。
