# sdd-frl CLI 契约

## 命令

| 命令 | 输入 | 输出 |
|---|---|---|
| `sdd-frl init [PATH]` | 当前本地目录；可选 `--timezone` | 配置、Agent TOML、运行契约和三步指南 |
| `sdd-frl prepare [PATH] --target <PATH>` | 本次任务唯一目标；可选日期或时间窗口 | 下一步 handoff JSON |
| `sdd-frl continue [PATH]` | `run_id`、阶段和 Agent 输出文件 | 校验结果及下一步 handoff JSON |
| `sdd-frl finalize [PATH]` | 已完成或失败的 `run_id` | `STOP` handoff 与最终报告路径 |
| `sdd-frl run [PATH] --target <PATH>` | 与 `prepare` 相同 | 兼容别名；不启动嵌套 Codex |
| `sdd-frl validate` | 产物种类和 JSON 文件 | Schema 校验结果 |
| `sdd-frl validate-examples` | 无 | 内置有效/无效示例的回归结果 |

## 初始化

初始化只创建当前目录的运行配置，不接收、不保存目标：

```powershell
sdd-frl init .
```

配置 Schema 版本为 `2.0.0`，只包含时区、运行目录、报告目录和 Codex 数据源位置。
采集固定保留原始内容，不提供脱敏开关。检测到旧配置时返回
`LEGACY_WORKSPACE_UNSUPPORTED`，不迁移、回填或改写。

## 运行目标

`--target` 是每个定时任务的必填运行参数，必须是绝对目录。CLI 由目标目录名确定本次
运行的 `project_id`，并把目标绝对路径写入本次 `run.json.parameters.target_root`。
它不写回配置。

`project_id` 继续存在于 source/evidence 等外部数据契约中，用于同一次运行的产物身份、
Schema 交叉校验和趋势隔离；它由本次目标即时派生，不是注册信息或持久映射。

两个任务可以使用同一个当前目录但传入不同目标。每次采集只接受
`session_meta.cwd` 位于本次目标之内的会话，其他目标计入
`skipped_outside_target`。

## 日期与失败

- 默认复盘配置时区中的最近一个完整自然日。
- `--date 2026-07-26` 复盘 `[2026-07-26 00:00, 2026-07-27 00:00)`。
- `--window-start` 和 `--window-end` 必须成对提供并带时区。
- 数据源不可用返回 `CODEX_SOURCE_UNAVAILABLE`。
- 没有找到目标对话返回 `TARGET_CONVERSATIONS_NOT_FOUND`。
- 只有目标对话已找到、但窗口内无可采集记录时，才进入 `COMPLETED_NO_TASKS`。

所有配置、锁、运行产物和报告必须留在当前目录。目标目录只读。
