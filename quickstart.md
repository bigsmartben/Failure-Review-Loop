# Quickstart

选择一种方式创建已安排任务（Scheduled task）。

## 方式一：直接新建

在 ChatGPT 中打开“已安排任务”，点击“新建”，填写：

| 字段 | 内容 |
|---|---|
| 标题 | `Failure Review Loop 每日复盘` |
| 描述 | 粘贴 [automation/task-prompt.md](automation/task-prompt.md) 的全部内容 |
| 运行于 | `新任务` |
| 项目 | `Failure-Review-Loop` |
| 模型 | `GPT-5.6 Sol` |
| 推理 | `最高` |
| 重复 | 按需选择，例如 `每天` |
| 时间 | 按需选择，例如 `9:00` |
| 通知 | `所有运行` |

确认无误后创建。

## 方式二：在项目对话中设置

打开本地项目 `Failure-Review-Loop`，发送：

```text
我们一起来设置一个已安排任务吧。首先，说明已安排任务在 ChatGPT 中的工作方式。然后询问我需要安排什么，以及应该在什么时候运行。
```

被询问时回答：

| 问题 | 示例回答 |
|---|---|
| 需要安排什么 | `在本地项目 Failure-Review-Loop 中，按照 automation/task-prompt.md 执行失败复盘。` |
| 什么时候运行 | `每天 9:00，时区 Asia/Shanghai。` |

检查项目、时间、模型和通知设置，然后确认创建。

## 首次准备

在仓库根目录复制并运行这一条命令：

```powershell
npm run init:product
```

它会自动安装依赖、创建安全的仅分析配置并完成全部自检。已有的 `failure-review.config.json` 不会被覆盖。看到“初始化完成，可以创建已安排任务”即可继续。

## 查看结果

命令会返回 `run_id` 和 `status`。打开报告：

```powershell
$runId = "<返回的 run_id>"
Get-Content "runs\$runId\report.md"
```

| 状态 | 含义 |
|---|---|
| `COMPLETED_NO_TASKS` | 时间窗口内没有可分析任务 |
| `COMPLETED_WITH_METRICS` | 已生成指标 |
| `COMPLETED_WITH_FINDINGS` | 已生成问题报告，没有可执行提案 |
| `COMPLETED_WITH_PROPOSAL` | 已生成供人工确认的提案 |
| `FAILED_*` | 查看 `report.md`、`run.json` 和 `logs/` |

本地已安排任务运行时，机器需要开机、ChatGPT 桌面端需要运行，Codex 账户需要保持登录。
