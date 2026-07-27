# Failure Review Loop 使用者快速开始

只做下面三步。

## 1. 安装

复制到 PowerShell 执行：

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.4.0"
```

## 2. 初始化

进入你要复盘的项目根目录，执行：

```powershell
sdd-frl init .
```

## 3. 复制、粘贴、发送

在 Codex App 打开刚完成初始化的项目。复制下面代码框里的整句话，粘贴到该项目
的 Codex 对话，然后发送：

```text
请读取当前项目的 `.sdd-frl/automation/task-prompt.md`，并严格按照文件内容创建定时任务。
```

确认卡中的工作区、频率、时区和“本地项目”无误后确认创建。Codex 回复任务名称、
工作区、频率、时区、运行位置和“已启用”，就完成了。

复盘结果会写入 `docs/failure-review/YYYY-MM-DD.md`。

如果 Codex 返回 `SETUP_BLOCKED`，把原因交给维护者处理。
