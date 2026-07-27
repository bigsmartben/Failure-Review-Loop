# sdd-frl 工作区定时任务

本任务只复盘它所绑定的当前工作区。不要到 `Failure-Review-Loop` 或其他项目中运行。

1. 确认当前目录存在 `.sdd-frl/config.json` 与 `failure-review.project.json`。
2. 执行 `sdd-frl run .`。CLI 会使用工作区配置的时区复盘最近一个完整自然日。
3. 打开命令返回的 `report` 路径并报告状态、目标达成率、执行效能和主要问题。
4. 失败时报告稳定错误码与 `.sdd-frl/runs/<run_id>/report.md`；不得把失败或空结果称为成功。
5. Optimizer 只生成提案，不应用、提交、发布或部署修改。

所有中间产物、锁和最终文档必须留在当前工作区内。
