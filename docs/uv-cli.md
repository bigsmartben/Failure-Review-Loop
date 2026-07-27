# sdd-frl CLI 契约

## 安装

`uv tool install` 接受 Python 包规格。当前仓库通过 `pyproject.toml` 暴露 `sdd-frl` 控制台入口：

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.4.0"
```

使用 Git 标签而不是浮动分支，确保定时任务可以复现同一版本。

## 命令

| 命令 | 输入 | 输出 |
|---|---|---|
| `sdd-frl init [PATH]` | FRL 工作区；必须用 `--analysis-target` 指定另一个 Codex 项目 | 用户指南、业务配置、Agent TOML、运行契约和设置提示词 |
| `sdd-frl prepare [PATH]` | FRL 工作区；可选日期或显式时间窗口 | 从已绑定分析目标采集后的下一步 handoff JSON |
| `sdd-frl continue [PATH]` | `run_id`、阶段和 Agent 输出文件 | 校验结果及下一步 handoff JSON |
| `sdd-frl finalize [PATH]` | 已完成或失败的 `run_id` | `STOP` handoff 与最终报告路径 |
| `sdd-frl run [PATH]` | 与 `prepare` 相同 | 兼容别名；不启动嵌套 `codex exec` |
| `sdd-frl probe [PATH]` | 已初始化工作区 | 项目身份、Agent 配置、session 根可访问性与目标绑定样本 |
| `sdd-frl validate` | 产物种类和 JSON 文件 | Schema 校验结果 |
| `sdd-frl validate-examples` | 无 | 内置有效/无效示例的回归结果 |

需要 Analyst 时，`prepare` 的标准输出：

```json
{
  "run_id": "20260727T010000Z_my-project_a1b2c3",
  "status": "ANALYZING",
  "next_action": "SPAWN_ANALYST",
  "input_packet": {
    "stage": "analyst",
    "agent": "sdd_frl_analyst",
    "prompt": "C:/work/my-project/.sdd-frl/contracts/analyst.md",
    "input_files": {
      "run": "C:/work/my-project/.sdd-frl/runs/<run_id>/run.json",
      "evidence": "C:/work/my-project/.sdd-frl/runs/<run_id>/evidence.json"
    },
    "output_file": "C:/work/my-project/.sdd-frl/runs/<run_id>/agent-output/analyst.json"
  },
  "output_schema": "C:/work/my-project/.sdd-frl/contracts/findings.schema.json",
  "blocker_codes": [],
  "report": null
}
```

`next_action` 只有 `SPAWN_ANALYST`、`SPAWN_OPTIMIZER`、`FINALIZE` 和 `STOP`。
Codex App 只按该枚举路由；Prompt 不负责判断 readiness（就绪状态）。

## 初始化边界

- `PATH` 是执行初始化的 FRL 工作区；`init` 不暗中切换到分析目标。
- `--analysis-target` 是只读采集目标；初始化器不在该目录创建或修改文件。
- 新工作区缺少 `--analysis-target` 时返回 `ANALYSIS_TARGET_REQUIRED`；分析目标与
  FRL 工作区相同时返回 `ANALYSIS_TARGET_MUST_DIFFER`。
- FRL 工作区 ID 优先采用已有 `failure-review.project.json`，否则使用
  `--project-id`，最后才由 FRL 工作区目录名生成。
- 分析项目 ID 使用 `--analysis-project-id`；未提供时由分析目标目录名生成。
- 已配置外部分析目标后，不带 `--analysis-target` 再次执行 `init` 必须保持原绑定，
  不得回退到 FRL 工作区。
- 已有标记、配置与参数冲突时返回 `INIT_CONFLICT`，不覆盖。
- `README.md` 与 `quickstart.md` 生成在项目根目录；前者面向维护者，后者面向首次使用者。
- 已有同名项目文档会保留，不覆盖。
- 旧版自动生成的 `.sdd-frl/README.md` 与 `.sdd-frl/quickstart.md` 只有在内容与旧模板完全一致时才删除；自定义内容保留。
- 生成的 `.sdd-frl/automation/task-prompt.md` 可随模板升级；用户自定义提示词不会被覆盖。
- 生成 `.codex/agents/sdd-frl-analyst.toml` 与
  `.codex/agents/sdd-frl-optimizer.toml`。同路径自定义文件不会被覆盖，而是返回
  `FRL_AGENT_CONFLICT`。
- 旧 `.sdd-frl/config.json.models` 会一次性迁移到 Agent TOML，业务配置中不再保存模型。
- Agent 读取的 Prompt、Schema 与契约复制到 `.sdd-frl/contracts/`，避免依赖工作区外路径。
- 旧版 `failure-review.config.json` 只导入与当前根目录精确匹配的项目配置。

## 运行和日期

- `sdd-frl prepare .`：复盘配置时区中的最近一个完整自然日。
- `sdd-frl prepare . --date 2026-07-26`：复盘该日期的 `[00:00, 次日00:00)`。
- `--window-start` 和 `--window-end` 必须成对提供，且都带时区。
- 最终文档使用窗口起点在配置时区中的日期，固定命名为 `YYYY-MM-DD.md`。
- 每次运行都有唯一 `run_id`；同日成功重跑更新日期文档，但原始运行目录全部保留。
- 失败重跑不覆盖同日已有的成功文档。
- `source-records.json` 必须通过 `source-records.schema.json`，并包含来源、
  `empty_reason` 与 `collection_summary`。窗口是半开区间，结束时刻及当前日数据
  不进入上一个完整自然日的结果。

空采集不是一个统一事实：

| 采集事实 | 结果 |
|---|---|
| session 根不存在、不可读或不可枚举 | `FAILED_COLLECTION` / `CODEX_SOURCE_UNAVAILABLE` |
| 数据源可读，但没有对话绑定分析目标 | `FAILED_COLLECTION` / `ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND` |
| 已匹配目标对话，窗口内无事件 | `COMPLETED_NO_TASKS` / `NO_EVENTS_IN_WINDOW` |
| 窗口内有原始事件，但全部不可采集 | `COMPLETED_NO_TASKS` / `EVENTS_IN_WINDOW_UNCOLLECTABLE` |

## 安全与失败语义

所有配置路径经过规范化。运行目录、锁、临时文件和最终文档必须位于 FRL
工作区内；改进载体必须位于分析目标内，并且只读。

| 错误码 | 行为 |
|---|---|
| `WORKSPACE_NOT_INITIALIZED` | 停止并要求先执行 `init` |
| `WORKSPACE_PROJECT_MISMATCH` | 停止，不猜测或切换项目 |
| `WORKSPACE_PATH_ESCAPE` | 停止，不在工作区外写文件 |
| `ANALYSIS_TARGET_REQUIRED` | 停止，要求显式绑定另一个 Codex 项目目录 |
| `ANALYSIS_TARGET_INVALID` | 停止，分析目标配置结构不合法 |
| `ANALYSIS_TARGET_NOT_DIRECTORY` | 停止，分析目标路径不存在或不是目录 |
| `ANALYSIS_TARGET_MUST_DIFFER` | 停止，分析目标与 FRL 工作区不能相同 |
| `ANALYSIS_TARGET_PATH_ESCAPE` | 停止，不读取分析目标之外的改进载体 |
| `CODEX_SOURCE_UNAVAILABLE` | 采集失败；不得降级为 `COMPLETED_NO_TASKS` |
| `ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND` | 采集失败；不得声称目标项目没有任务 |
| `FRL_AGENT_CONFLICT` | 停止，不覆盖同路径自定义 Agent |
| `AGENT_CONFIG_UNAVAILABLE` | 停止，要求重新初始化或修复 Agent TOML |
| `AGENTS_DISABLED` | 停止，项目级 Codex 配置禁用了原生子代理 |
| `STAGE_ORDER_INVALID` | 停止，不跳过或重复阶段 |
| `RUN_IDENTITY_MISMATCH` | 失败并停止，不接受其他运行或项目的输出 |
| `AGENT_OUTPUT_INVALID` | 失败并停止，保留候选输出与报告 |
| `OVERLAPPING_RUN` | 停止，保留当前活动运行 |
| `TIMEZONE_REQUIRED` | 停止并要求提供合法 IANA 时区 |
| `INVALID_REVIEW_DATE` | 停止，不创建运行目录 |

Codex 会话源、分析目标和 uv 工具环境可以位于 FRL 工作区外，但只能由 sdd-frl
只读使用。
