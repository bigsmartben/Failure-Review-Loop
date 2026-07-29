# Failure Review Loop 使用者快速开始

只做下面三步。

## 1. 安装

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.4.1"
```

## 2. 初始化当前本地目录

```powershell
sdd-frl init .
```

## 3. 在当前项目的 Codex 对话框输入

```text
请读取 `.sdd-frl/automation/task-prompt.md`，为以下分析目标创建一个独立的 FRL 定时任务。

分析目标：<目标项目绝对路径>
```
