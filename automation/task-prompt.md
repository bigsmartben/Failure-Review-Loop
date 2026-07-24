# Failure Review Loop 定时任务入口

在本地项目 `Failure-Review-Loop` 中运行一次失败复盘。不要并行启动阶段，不要直接修改任何改进载体。

1. 根据任务配置确定 `project_id`、带时区的 `[window_start, window_end)` 和 `timezone`。改进载体从配置文件读取，不是运行前提。运行会锁定当前契约身份；契约变化后必须开始新运行。
2. 先运行 `npm run probe`；能力探测失败时停止并报告。
3. 调用：

```powershell
node src/cli.js run --config failure-review.config.json --project-id <project_id> --window-start <ISO> --window-end <ISO> --timezone <IANA timezone>
```

4. 打开命令返回的 `runs/<run_id>/report.md` 并向用户报告结果。
5. 若状态为 `FAILED_*`，报告失败阶段、错误码和日志路径；不得把空结果称为成功。
6. 若状态为 `COMPLETED_NO_TASKS`，明确写“本周期没有可分析任务”。
7. 若状态为 `COMPLETED_WITH_METRICS`，报告达成率、结果覆盖率、效能指标和趋势，不把无提案称为失败。
8. 若状态为 `COMPLETED_WITH_FINDINGS`，报告高频问题及未生成提案的具体原因。
9. 若状态为 `COMPLETED_WITH_PROPOSAL`，只展示提案供人工确认；不要应用提案、提交或发布。

报告趋势时必须说明它是观察结果，不代表载体修改与结果变化存在确定因果关系。

每次运行必须从保存的任务参数重新计算时间窗口，不能复用上一轮窗口。重试同一次运行时使用原 `run_id` 和完全相同的范围参数。
