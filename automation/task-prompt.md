# sdd-frl Codex App 设置提示词模板

此文件仅说明模板职责。用户应复制 FRL 工作区执行
`sdd-frl init . --analysis-target <PATH>` 后生成的
`.sdd-frl/automation/task-prompt.md`，因为生成文件包含 FRL 工作区、分析目标、
项目 ID 和时区。

生成的提示词负责：

1. 请求 Codex App 创建每天 09:00 的定时任务。
2. 只在 FRL 工作区执行 CLI，只复盘绑定的另一个 Codex 项目目录；创建前分别校验两个路径、
   项目身份、项目可信状态、原生 Agent 可用性和权限。
3. 首期只允许本地项目（local project）运行，不选择 worktree。
4. 通过 `prepare → continue → finalize` handoff 状态机编排
   `sdd_frl_analyst` 与 `sdd_frl_optimizer` 原生子代理。
5. 禁止在 Python/CLI 中嵌套调用 `codex exec`，并禁止跳过 Schema、阶段顺序和
   `run_id` 校验。
6. 命令参数必须取自当前 handoff 字段，不得省略、复用或原样传递占位符。
7. 所有中间产物、锁和最终文档必须留在 FRL 工作区；分析目标只读。
8. 要求失败时返回稳定 blocker code（阻塞码），不把空结果或未完成状态称为成功。
