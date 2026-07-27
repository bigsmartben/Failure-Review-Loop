<!-- sdd-frl-generated: codex-automation-setup-v3 -->
# 请在 Codex App 中创建工作区定时任务

## 设置契约

你正在执行一次性设置，不是在运行复盘。FRL 工作区与分析目标固定为：

- 名称：`sdd-frl-harness`
- 频率：每天 09:00
- 时区：`Asia/Shanghai`
- FRL 工作区：`C:\Users\24598\Documents\github\Failure-Review-Loop`
- 分析目标：`C:\Users\24598\Documents\github\harness`
- 分析项目 ID：`harness`
- 运行位置：本地项目（local project），首期不得选择 worktree

创建前必须依次验证：

1. 当前项目绝对路径等于 FRL 工作区 `C:\Users\24598\Documents\github\Failure-Review-Loop`，并且 `.sdd-frl/config.json` 与
   `failure-review.project.json` 的 `project_id` 都是 `failure-review-loop`；
2. 配置中的 `analysis_target.workspace_root` 等于 `C:\Users\24598\Documents\github\harness`，
   `analysis_target.project_id` 等于 `harness`，且分析目标目录存在；
3. 当前项目已被 Codex 信任，项目级 `.codex/agents/` 配置已加载；
4. 可按名称调用 `sdd_frl_analyst` 和 `sdd_frl_optimizer` 两个原生
   subagent（子代理）；
5. 运行 `sdd-frl probe .`，结果中的 `ready` 为 `true`，且返回的
   `analysis_target` 与上述分析目标一致；
6. 定时任务具有 FRL 工作区写权限与分析目标只读权限。不得请求 FRL 工作区外写入
   或网络权限。

任一验证失败时停止创建，回复对应稳定错误码：
`WORKSPACE_MISMATCH`、`PROJECT_NOT_TRUSTED`、`AGENT_CONFIG_UNAVAILABLE`、
`AGENTS_DISABLED`、`ANALYSIS_TARGET_REQUIRED`、`ANALYSIS_TARGET_INVALID`、
`ANALYSIS_TARGET_NOT_DIRECTORY`、`ANALYSIS_TARGET_MUST_DIFFER`、
`CODEX_SOURCE_UNAVAILABLE`、`ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND`、
`WORKSPACE_WRITE_REQUIRED` 或
`SCHEDULE_PERMISSION_DENIED`。不要猜测、修复或改绑其他项目。
如果用户要求改为 worktree，首期返回 `SETUP_BLOCKED`；若 `.codex/agents/`、
`.sdd-frl/contracts/` 或任务提示词尚未提交，同时报告
`WORKTREE_REQUIRES_COMMIT`。

验证通过后，先向用户展示名称、FRL 工作区、分析目标、频率、时区、运行位置和权限的确认卡。
只有用户确认后，才创建并启用定时任务（scheduled task / automation）。

## 定时任务执行提示词

创建的任务必须逐字保存以下执行提示词：

> 只在 FRL 工作区 `C:\Users\24598\Documents\github\Failure-Review-Loop` 执行 CLI，只复盘分析目标 `C:\Users\24598\Documents\github\harness`。
> 不得把 FRL 工作区误当成分析目标，也不得切换到第三个项目。
> 首先执行 `sdd-frl prepare .` 并解析返回的 handoff JSON。
> 只根据 `next_action` 执行下一步，不得从自然语言猜测阶段：
> - `SPAWN_ANALYST`：调用原生子代理 `sdd_frl_analyst`，把
>   `input_packet`、`output_schema` 和其中列出的只读文件交给它。
>   将子代理返回的纯 JSON 原样写入 `input_packet.output_file`，然后执行
>   `sdd-frl continue . --run-id <run_id> --stage analyst --input <output_file>`。
> - `SPAWN_OPTIMIZER`：同样调用 `sdd_frl_optimizer`，保存纯 JSON 后执行
>   `sdd-frl continue . --run-id <run_id> --stage optimizer --input <output_file>`。
> - `FINALIZE`：执行 `sdd-frl finalize . --run-id <run_id>`。
> - `STOP`：停止，不再调用任何下游阶段。
> 命令中的 `<run_id>` 与 `<output_file>` 是字段占位符：每次都必须分别替换为
> 当前 handoff 的 `run_id` 与 `input_packet.output_file`；不得省略、原样传递或沿用上一次运行的值。
> 每次 CLI 调用后都重新解析 handoff JSON，直到 `next_action` 为 `STOP`。
> 不得调用嵌套的 `codex exec`。不得跳过 CLI 的 JSON Schema 校验、阶段顺序校验
> 或运行身份校验。子代理不得修改文件；Optimizer 只返回提案。
> 最后打开 handoff 的 `report` 路径，报告状态、目标达成率、执行效能和主要问题。
> 失败时报告全部 `blocker_codes` 与 `.sdd-frl/runs/<run_id>/report.md`，
> 不得把失败、空输出或未完成状态称为成功。
> 所有候选输出、中间产物、锁和最终文档必须留在 FRL 工作区 `C:\Users\24598\Documents\github\Failure-Review-Loop` 内；
> 分析目标 `C:\Users\24598\Documents\github\harness` 只读。

创建完成后，只回复任务名称、FRL 工作区、分析目标、频率、时区、运行位置和启用状态。
如果当前环境不能创建定时任务，回复 `SETUP_BLOCKED` 和具体原因；不得声称任务已经创建。
