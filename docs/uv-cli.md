# sdd-frl CLI 契约

## 安装

`uv tool install` 接受 Python 包规格。当前仓库通过 `pyproject.toml` 暴露 `sdd-frl` 控制台入口：

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.2.0"
```

使用 Git 标签而不是浮动分支，确保定时任务可以复现同一版本。

## 命令

| 命令 | 输入 | 输出 |
|---|---|---|
| `sdd-frl init [PATH]` | 目标工作区；可选项目 ID 与 IANA 时区 | 工作区配置、标记、任务提示词和产物目录 |
| `sdd-frl run [PATH]` | 工作区；可选日期或显式时间窗口 | JSON 运行摘要及日期 Markdown |
| `sdd-frl probe [PATH]` | 已初始化工作区 | Codex CLI 能力与项目身份 |
| `sdd-frl validate` | 产物种类和 JSON 文件 | Schema 校验结果 |
| `sdd-frl validate-examples` | 无 | 内置有效/无效示例的回归结果 |

`run` 成功时的标准输出：

```json
{
  "run_id": "20260727T010000Z_my-project_a1b2c3",
  "status": "COMPLETED_WITH_METRICS",
  "project_id": "my-project",
  "review_date": "2026-07-26",
  "report": "C:/work/my-project/docs/failure-review/2026-07-26.md"
}
```

## 初始化边界

- `PATH` 本身就是工作区根目录；`init` 不暗中切换到父级。
- 项目 ID 优先采用已有 `failure-review.project.json`，否则使用 `--project-id`，最后才由目录名生成。
- 已有标记、配置与参数冲突时返回 `INIT_CONFLICT`，不覆盖。
- 旧版 `failure-review.config.json` 只导入与当前根目录精确匹配的项目配置；工作区外载体不会导入。

## 运行和日期

- `sdd-frl run .`：复盘配置时区中的最近一个完整自然日。
- `sdd-frl run . --date 2026-07-26`：复盘该日期的 `[00:00, 次日00:00)`。
- `--window-start` 和 `--window-end` 必须成对提供，且都带时区。
- 最终文档使用窗口起点在配置时区中的日期，固定命名为 `YYYY-MM-DD.md`。
- 每次运行都有唯一 `run_id`；同日成功重跑更新日期文档，但原始运行目录全部保留。
- 失败重跑不覆盖同日已有的成功文档。

## 安全与失败语义

所有配置路径经过规范化；运行目录、锁、临时文件、改进载体和最终文档必须位于工作区内。

| 错误码 | 行为 |
|---|---|
| `WORKSPACE_NOT_INITIALIZED` | 停止并要求先执行 `init` |
| `WORKSPACE_PROJECT_MISMATCH` | 停止，不猜测或切换项目 |
| `WORKSPACE_PATH_ESCAPE` | 停止，不在工作区外写文件 |
| `OVERLAPPING_RUN` | 停止，保留当前活动运行 |
| `TIMEZONE_REQUIRED` | 停止并要求提供合法 IANA 时区 |
| `INVALID_REVIEW_DATE` | 停止，不创建运行目录 |

Codex 会话源和 uv 工具环境可以位于工作区外，但只能由 sdd-frl 只读使用。
