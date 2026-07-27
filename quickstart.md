# 三步完成 sdd-frl 设置

用户不需要手工运行复盘命令，也不需要自行配置计划任务。

## 1. 安装 CLI

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.3.0"
```

`uv` 的命令是单数 `tool`，不是 `tools`。

## 2. 初始化目标项目

在目标项目根目录执行：

```powershell
sdd-frl init .
```

这里不能使用 `uv init .`；后者创建的是 Python 项目，不会初始化 Failure Review Loop。

初始化会生成：

```text
目标项目/
├─ failure-review.project.json
├─ .sdd-frl/
│  ├─ README.md
│  ├─ quickstart.md
│  ├─ config.json
│  ├─ automation/task-prompt.md
│  ├─ runs/
│  └─ locks/
└─ docs/failure-review/
```

## 3. 粘贴提示词

打开目标项目中的 `.sdd-frl/automation/task-prompt.md`，复制全文，在 Codex App
当前项目的对话中发送。

提示词已经包含目标工作区绝对路径、项目 ID、时区和每天 09:00 的频率。Codex App
应创建定时任务并返回任务名称、工作区、频率、时区和启用状态。

用户不需要手工运行复盘；定时任务内部执行 `sdd-frl run .`。任务不能绑定到中央 `Failure-Review-Loop` 运行器，也不能切换到其他工作区。

最终复盘文档固定写入：

```text
docs/failure-review/YYYY-MM-DD.md
```
