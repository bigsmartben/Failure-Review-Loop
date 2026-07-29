<!-- issue-12-user-e2e-v1 -->
# Issue #12 用户 E2E 验收

E2E（端到端）验收从用户操作开始，一直检查到定时任务实际采集数据并产生运行结果。

## 验收目标

确认用户只需要：

1. 安装当前版本；
2. 在当前项目执行 `sdd-frl init .`；
3. 在 Codex 对话框输入一个分析目标。

系统应创建一个独立且已启用的定时任务。用户没有填写调度参数时，默认每天 `22:00` 运行。任务运行时只采集该目标的 Codex 本地会话，采集结果继续满足 source/evidence（来源记录/证据）契约。

## 准备条件

- Windows PowerShell、Codex App 和 `uv` 可用。
- 准备一个新的空目录作为验收目录，例如 `C:\work\frl-issue-12-e2e`。
- 准备两个真实目标目录，例如：
  - 目标 A：`C:\work\product-a`
  - 目标 B：`C:\work\product-b`
- 目标 A、目标 B 各自至少有一条在对应目录中产生的 Codex 本地会话。
- 验收使用用户本地数据，不要求脱敏。

以下示例变量可按实际路径修改：

```powershell
$repo = "C:\path\to\Failure-Review-Loop"
$acceptanceDir = "C:\work\frl-issue-12-e2e"
$targetA = "C:\work\product-a"
$targetB = "C:\work\product-b"
```

## E2E-01：安装和干净初始化

执行：

```powershell
Set-Location $repo
uv tool install --force .

New-Item -ItemType Directory -Force $acceptanceDir | Out-Null
Set-Location $acceptanceDir
sdd-frl init .
sdd-frl init .
```

验收：

- 第一次初始化返回 `initialized`。
- 第二次初始化返回 `already_initialized`，不会覆盖已有运行数据。
- `.sdd-frl/config.json` 只保存运行配置，不保存分析目标。
- 生成的 `quickstart.md` 只包含安装、初始化、在 Codex 输入分析目标三步。

检查配置字段：

```powershell
$config = Get-Content .sdd-frl/config.json -Raw | ConvertFrom-Json
$config.PSObject.Properties.Name | Sort-Object
```

期望只有：

```text
codex_home
reports_dir
runs_dir
schema_version
timezone
```

## E2E-02：旧入口已经删除

执行：

```powershell
$removedInitFlag = "--analysis" + "-target"
sdd-frl init . $removedInitFlag $targetA

$removedCommand = "pro" + "be"
sdd-frl $removedCommand
```

验收：

- 两条命令都由参数解析器直接判定为未知参数或未知命令。
- 不出现“仍可继续使用”“自动迁移”或“已替换成新绑定”的兼容行为。
- 已初始化目录的配置不发生变化。

## E2E-03：缺少分析目标时只询问目标

在验收目录对应的 Codex 对话框输入：

```text
请读取 `.sdd-frl/automation/task-prompt.md`，创建一个独立的 FRL 定时任务。
```

验收：

- Codex 只询问“分析目标是什么”。
- 不询问当前目录、运行目录、内部项目 ID、权限或其他内部参数。
- 不扫描目录、不猜测目标、不创建任务。

## E2E-04：默认调度只确认三个用户参数

在 Codex 对话框输入：

```text
请读取 `.sdd-frl/automation/task-prompt.md`，为以下分析目标创建一个独立的 FRL 定时任务。

分析目标：C:\work\product-a
```

将示例路径替换成 `$targetA` 的实际值。

验收：

- 创建前只确认：
  - 分析目标：目标 A；
  - 运行频率：每天；
  - 运行时间：`22:00`。
- 确认内容不展示当前目录、内部项目 ID、权限和 Agent（执行代理）配置。
- 用户确认后，创建并启用一个任务。
- 完成回复只说明分析目标、每天、`22:00` 和已启用。

## E2E-05：自定义调度覆盖默认值

为目标 B 发送：

```text
请读取 `.sdd-frl/automation/task-prompt.md`，为以下分析目标创建一个独立的 FRL 定时任务。

分析目标：C:\work\product-b
运行频率：每周一至周五
运行时间：20:30
```

将示例路径替换成 `$targetB` 的实际值。

验收：

- 确认内容只包含目标 B、每周一至周五、`20:30`。
- 用户确认后，创建并启用第二个任务。
- 系统不把目标 A 和目标 B 合并到一个任务。

## E2E-06：两个目标的任务相互独立

在 Codex 的任务列表中检查并分别手动触发两个任务。

验收：

- 存在两个已启用的独立任务。
- 目标 A 的任务只保存目标 A，目标 B 的任务只保存目标 B。
- 目标 A 任务使用每天 `22:00`；目标 B 任务使用每周一至周五 `20:30`。
- 暂停或修改目标 B 的任务，不影响目标 A 的任务。

## E2E-07：实际采集只命中对应目标

分别手动触发目标 A 和目标 B 的任务。每次运行完成后，在验收目录执行：

```powershell
$latestRuns = Get-ChildItem .sdd-frl/runs -Directory |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 2

$latestRuns | ForEach-Object {
  Get-Content (Join-Path $_.FullName "run.json") -Raw | ConvertFrom-Json |
    Select-Object run_id, status, @{Name="target"; Expression={$_.parameters.target_root}}
}
```

验收：

- 两次运行的 `target` 分别等于目标 A 和目标 B 的绝对路径。
- 目标 A 的 `source-records.json` 只包含目标 A 的 Codex 会话。
- 目标 B 的 `source-records.json` 只包含目标 B 的 Codex 会话。
- 任务不修改目标项目中的文件。
- 报告按目标分别输出，不互相覆盖。

具体检查示例：如果目标 A 的已知会话中包含文本 `A_ONLY_E2E_MARKER`，目标 B 的会话中包含 `B_ONLY_E2E_MARKER`，则 A 的来源记录只能命中前者，B 的来源记录只能命中后者。

## E2E-08：找不到目标会话时如实失败

准备一个存在但从未产生 Codex 会话的新目录，将它作为新任务的分析目标并手动触发。

验收：

- 运行状态为 `FAILED_COLLECTION`。
- 阻断码包含 `TARGET_CONVERSATIONS_NOT_FOUND`。
- 结果不宣称成功，不回退到目标绑定或注册步骤。

如果 Codex 本地数据源本身不可读，则应返回 `CODEX_SOURCE_UNAVAILABLE`，同样不得宣称成功。

## E2E-09：采集数据契约回归

回到仓库目录执行：

```powershell
Set-Location $repo
uv run pytest -q
npm test
uv run sdd-frl validate-examples
```

验收：

- 三条命令全部退出码为 `0`。
- Python 和 Node.js 测试全部通过。
- source/evidence 示例契约全部通过。
- 采集内容保持用户本地原始数据，不新增脱敏转换。

## E2E-10：旧设计零残留

在仓库目录执行：

```powershell
$forbidden = @(
  "--analysis" + "-target",
  "--analysis" + "-project-id",
  "analysis" + "_target",
  "analysis" + "_project_id",
  "sdd-frl " + "probe",
  "ANALYSIS" + "_TARGET_REQUIRED",
  "ANALYSIS" + "_TARGET_INVALID",
  "ANALYSIS" + "_TARGET_MUST_DIFFER"
)

$forbidden | ForEach-Object {
  rg -n --fixed-strings -- $_ .
}
```

验收：所有搜索均为零结果。

## 验收记录

| 场景 | 结果 | 证据 |
|---|---|---|
| E2E-01 安装和初始化 | 待执行 | 初始化输出、配置字段 |
| E2E-02 旧入口删除 | 待执行 | 参数解析错误、配置未变化 |
| E2E-03 缺少目标 | 待执行 | Codex 回复截图 |
| E2E-04 默认调度 | 待执行 | 确认卡、任务详情 |
| E2E-05 自定义调度 | 待执行 | 确认卡、任务详情 |
| E2E-06 双任务隔离 | 待执行 | 任务列表、修改前后截图 |
| E2E-07 实际采集隔离 | 待执行 | 两份运行记录和来源记录 |
| E2E-08 失败真实性 | 待执行 | 运行状态、阻断码 |
| E2E-09 契约回归 | 待执行 | 三条命令输出 |
| E2E-10 零残留 | 待执行 | 搜索输出 |

## 通过条件

- E2E-01 至 E2E-10 全部通过。
- 没有目标串读、虚假成功、旧入口兼容或配置持久绑定。
- 数据采集和 source/evidence 契约回归全部通过。
