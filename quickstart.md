# Quickstart

已安排任务（Scheduled task）涉及两个不同的项目，不能混用：

| 角色 | 值 | 用途 |
|---|---|---|
| 运行器项目（runner project） | `Failure-Review-Loop` | 任务实际运行的位置；包含 `package.json`、`src/cli.js` 和任务提示词 |
| 被复盘项目（target project） | `failure-review.config.json` 中的 `project_id` | 需要分析的项目，例如 `pre-sdd`；它不需要包含 Failure Review Loop 的文件 |

已安排任务必须绑定到 `Failure-Review-Loop`。不要把任务绑定到被复盘项目，也不要让任务在被复盘项目中读取 `automation/task-prompt.md`。

## 1. 首次准备

在 `Failure-Review-Loop` 仓库根目录运行：

```powershell
npm run init:product
```

它会自动安装依赖、创建安全的仅分析配置并完成全部自检。已有的 `failure-review.config.json` 不会被覆盖。该步骤只初始化运行器，不会猜测你要复盘哪个项目。

显式注册被复盘项目。例如，ChatGPT 项目名为 `pre-sdd`、实际目录为 `C:\Users\24598\Documents\github\psp`：

```powershell
npm run configure:project -- `
  --project-id pre-sdd `
  --project-root "C:\Users\24598\Documents\github\psp"
```

该命令会以仅分析模式把绑定追加到 `failure-review.config.json`，并在目标根目录安全创建 `failure-review.project.json`。重复执行是幂等的，不会重复添加；目录或标记已属于其他项目时会拒绝修改。

复制任务提示词全文：

```powershell
Get-Content -Raw .\automation\task-prompt.md | Set-Clipboard
```

## 2. 创建已安排任务

选择下列一种方式。

### 方式一：直接新建

在 ChatGPT 中打开“已安排任务”，点击“新建”，填写：

| 字段 | 内容 |
|---|---|
| 标题 | `Failure Review Loop 每日复盘` |
| 描述 | 先填写 `目标 project_id: <配置中的项目 ID>`，再粘贴 [automation/task-prompt.md](automation/task-prompt.md) 的全部内容；不要只填写文件路径 |
| 运行于 | `新任务` |
| 项目 | `Failure-Review-Loop` |
| 模型 | `GPT-5.6 Sol` |
| 推理 | `最高` |
| 重复 | 按需选择，例如 `每天` |
| 时间 | 按需选择，例如 `9:00` |
| 通知 | `所有运行` |

确认无误后创建。

### 方式二：在项目对话中设置

打开本地项目 `Failure-Review-Loop`，发送：

```text
我们一起来设置一个已安排任务吧。首先，说明已安排任务在 ChatGPT 中的工作方式。然后询问我需要安排什么，以及应该在什么时候运行。
```

被询问时回答：

| 问题 | 示例回答 |
|---|---|
| 需要安排什么 | 先填写 `目标 project_id: <配置中的项目 ID>`，再粘贴剪贴板中的任务提示词全文 |
| 什么时候运行 | `每天 9:00，时区 Asia/Shanghai。` |

创建卡片中必须显示项目为 `Failure-Review-Loop`。如果显示 `pre-sdd` 等被复盘项目，取消创建并切换到运行器项目；不要让助手在被复盘项目中搜索或复制 Failure Review Loop 文件。

## 3. 查看结果

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
