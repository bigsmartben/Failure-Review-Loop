# 定时任务配置

Codex CLI 0.145.0 没有 Scheduled（定时任务）的创建或管理接口。首版采用官方支持的方式：

1. 运行 `npm run init:product`，创建不含敏感信息的仅分析配置。
2. 运行 `npm run configure:project -- --project-id <ID> --project-root <路径>`，显式注册被复盘项目。
3. 如需优化提案，再为该绑定配置 `improvement_target_ids`；仅分析时保持空数组。
4. 在普通会话中先手工执行一次 `node src/cli.js run ...`。
5. 在 ChatGPT 桌面端的 **Scheduled** 中创建任务，将项目固定为运行器项目 `Failure-Review-Loop`。
6. 在任务描述中先保存 `目标 project_id: <已注册的项目 ID>`，再粘贴 `automation/task-prompt.md` 的全文；不要只填写相对路径。
7. 被复盘项目不需要包含 `automation/task-prompt.md`、CLI 或其他 Failure Review Loop 文件。
8. 选择本地项目模式，确保机器在触发时开机且桌面端运行。
9. 设置时区和 RRULE；首次运行后核对 `run.json` 的窗口与时区。
10. 首次运行后抽查 `findings.json` 的任务覆盖、显式排除、结构化验收条件和交互事件。

项目注册命令的失败语义：

| 错误码 | 含义 |
|---|---|
| `CONFIG_NOT_INITIALIZED` | 尚未运行 `npm run init:product` |
| `PROJECT_ROOT_NOT_FOUND` | 目标目录不存在 |
| `PROJECT_ROOT_CONFLICT` | 同一目录已绑定到其他 `project_id` |
| `PROJECT_MARKER_CONFLICT` | 目标目录的标记声明了其他 `project_id` |

计划没有确定触发时间，因此仓库不擅自写死 RRULE。示例（每天 20:00）：

```text
RRULE:FREQ=DAILY;BYHOUR=20;BYMINUTE=0
```

该示例不是已激活的生产配置。
