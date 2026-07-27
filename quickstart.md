# Failure Review Loop 使用者快速开始

只做下面三步。

## 1. 安装

复制到 PowerShell 执行：

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.4.1"
```

## 2. 初始化

进入要作为 FRL 工作区的目录，把 `<目标项目路径>` 替换成另一个要复盘的
Codex 项目绝对路径：

```powershell
sdd-frl init . --analysis-target "<目标项目路径>"
```

## 3. 复制、粘贴、发送

在 Codex App 打开 FRL 工作区。复制下面代码框里的整句话，粘贴到该工作区
的 Codex 对话，然后发送：

```text
请读取当前项目的 `.sdd-frl/automation/task-prompt.md`，并严格按照文件内容创建定时任务。
```

确认卡中的 FRL 工作区、分析目标、频率、时区和“本地项目”无误后确认创建。
Codex 回复任务名称、FRL 工作区、分析目标、频率、时区、运行位置和“已启用”，
就完成了。

复盘结果会写入 `docs/failure-review/YYYY-MM-DD.md`。

如果 Codex 返回 `SETUP_BLOCKED`，把原因交给维护者处理。
