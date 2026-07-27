# Quickstart

定时任务（Scheduled task）必须绑定到它要复盘的目标项目。每个项目只需初始化一次。

## 1. 安装 CLI

本机 `uv` 命令使用单数 `tool`：

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.2.0"
sdd-frl --version
```

## 2. 初始化目标项目

进入目标项目根目录，例如 `C:\Users\24598\Documents\github\psp`：

```powershell
Set-Location C:\Users\24598\Documents\github\psp
sdd-frl init .
```

初始化会创建：

```text
psp/
├─ failure-review.project.json
├─ .sdd-frl/
│  ├─ config.json
│  ├─ automation/task-prompt.md
│  ├─ runs/
│  └─ locks/
└─ docs/failure-review/
```

重复执行 `sdd-frl init .` 是幂等操作，不覆盖有效配置。

## 3. 先手工验证

```powershell
sdd-frl probe .
sdd-frl run . --date 2026-07-26
```

省略 `--date` 时，CLI 使用 `.sdd-frl/config.json` 中的时区复盘最近一个完整自然日。

最终文档示例：

```text
docs/failure-review/2026-07-26.md
```

文件格式固定为 `docs/failure-review/YYYY-MM-DD.md`。

原始证据、指标和日志保存在 `.sdd-frl/runs/<run_id>/`。失败重跑不会覆盖已有的成功日期文档。

## 4. 创建定时任务

在 Codex 桌面端创建任务时：

| 字段 | 内容 |
|---|---|
| 项目 | 选择当前目标项目，例如 `psp` |
| 描述 | 粘贴 `.sdd-frl/automation/task-prompt.md` 全文 |
| 时间 | 按需设置，例如每天 09:00、`Asia/Shanghai` |

任务不能绑定到中央 `Failure-Review-Loop` 运行器，也不能写入其他项目。任务实际执行的命令是：

```powershell
sdd-frl run .
```

## 5. 常见失败

| 错误码 | 含义 |
|---|---|
| `WORKSPACE_NOT_INITIALIZED` | 当前项目尚未运行 `sdd-frl init .` |
| `WORKSPACE_PROJECT_MISMATCH` | 配置、标记或参数的项目 ID 不一致 |
| `WORKSPACE_PATH_ESCAPE` | 配置尝试把产物写到工作区外 |
| `OVERLAPPING_RUN` | 同一项目已有活动运行 |
| `INVALID_REVIEW_DATE` | 日期或时间窗口无效 |
