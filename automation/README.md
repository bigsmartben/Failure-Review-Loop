# 定时任务配置

Codex CLI 0.145.0 没有 Scheduled（定时任务）的创建或管理接口。首版采用官方支持的方式：

1. 复制 `failure-review.config.example.json` 为不含敏感信息的 `failure-review.config.json`。
2. 设置目标项目绑定，并用 `improvement_target_ids` 选择该项目允许读取的 `improvement_targets`；仅分析时可以绑定空数组。
3. 在普通会话中先手工执行一次 `node src/cli.js run ...`。
4. 在 ChatGPT 桌面端的 **Scheduled** 中创建本地项目任务，粘贴 `automation/task-prompt.md`。
5. 选择本地项目模式，确保机器在触发时开机且桌面端运行。
6. 设置时区和 RRULE；首次运行后核对 `run.json` 的窗口与时区。
7. 首次运行后抽查 `findings.json` 的任务覆盖、显式排除、结构化验收条件和交互事件。

计划没有确定触发时间，因此仓库不擅自写死 RRULE。示例（每天 20:00）：

```text
RRULE:FREQ=DAILY;BYHOUR=20;BYMINUTE=0
```

该示例不是已激活的生产配置。
