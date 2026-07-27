# 三步完成 sdd-frl 设置

## 1. 安装

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.3.0"
```

## 2. 在目标项目初始化

```powershell
sdd-frl init .
```

## 3. 在 Codex App 创建定时任务

打开 `.sdd-frl/automation/task-prompt.md`，复制全文，在 Codex App 当前项目的对话中发送。

不需要手工执行 `probe`、`run` 或配置计划任务；Codex App 会按照提示词创建绑定到当前工作区的每日任务。任务内部执行 `sdd-frl run .`，不能绑定到中央 `Failure-Review-Loop` 运行器。
