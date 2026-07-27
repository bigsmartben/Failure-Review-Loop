<!-- sdd-frl-generated: codex-automation-setup-v1 -->
# 请在 Codex App 中创建工作区定时任务

请为下面的目标工作区创建一个定时任务（scheduled task / automation）：

- 名称：`sdd-frl · failure-review-loop`
- 频率：每天 09:00
- 时区：`Asia/Shanghai`
- 目标工作区：`C:\Users\24598\Documents\github\Failure-Review-Loop`

定时任务的执行提示词必须是：

> 只复盘目标工作区 `C:\Users\24598\Documents\github\Failure-Review-Loop`，不得切换到其他项目或工作区。
> 确认 `.sdd-frl/config.json` 与 `failure-review.project.json` 存在，然后在该工作区执行 `sdd-frl run .`。
> 打开命令返回的 `report` 路径，报告状态、目标达成率、执行效能和主要问题。
> 失败时报告稳定错误码与 `.sdd-frl/runs/<run_id>/report.md`，不得把失败或空结果称为成功。
> Optimizer 只生成提案，不应用、提交、发布或部署修改。
> 所有中间产物、锁和最终文档必须留在目标工作区内。

创建前确认任务绑定的工作目录就是上述绝对路径。创建完成后，只回复任务名称、工作区、频率、时区和启用状态。
如果当前环境不能创建定时任务，回复 `SETUP_BLOCKED` 和具体原因；不得声称任务已经创建。
