# Failure Review Loop

按项目和时间窗口复盘 Codex 对话，衡量执行效能（efficiency）与用户目标达成率（attainment rate），并从至少三个独立任务重复出现的具体问题中生成改进提案。

## 推荐入口：sdd-frl

`sdd-frl` 是原生 Python CLI，通过 uv 的隔离工具环境安装；运行时不依赖 Node/npm。

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v0.2.0"
sdd-frl init .
sdd-frl run .
```

每个项目独立初始化。中间产物写入 `.sdd-frl/runs/<run_id>/`，最终文档按复盘日期写入
`docs/failure-review/YYYY-MM-DD.md`。同日重跑保留原始运行记录，并更新同一份最终文档。

完整安装、目录和失败语义见 [docs/uv-cli.md](docs/uv-cli.md)，定时任务设置见
[quickstart.md](quickstart.md)。

本项目采用契约优先（Contract-first）：领域契约先定义业务语义，Schema 定义结构，
Validator 执行跨产物规则，Prompt 和实现只能服从契约。权威顺序见
`docs/contracts/precedence.md`。

```text
Codex sessions
     │ 项目绑定 + 时间窗口
     ▼
source-records.json
     ▼
Collector ─校验─▶ evidence.json
                       ▼
Analyst ────────▶ findings.json
                       ▼
             metrics.json + trend.json
                       │
        同一具体问题跨 ≥ 3 个任务？
              否 ─────┴───── 是
              ▼              ▼
          指标报告      配置了项目载体？
                          否 ─┴─ 是
                          ▼      ▼
                      问题报告  Optimizer
                                  ▼
                            proposal.json
```

## 衡量什么

| 维度 | 指标 |
|---|---|
| 目标结果 | 已达成、未达成、未知、达成率、结果覆盖率 |
| 沟通效能 | 总轮次、澄清次数、重复澄清次数 |
| 执行效能 | 执行尝试次数、返工次数 |
| 高频模式 | 重复澄清、重复执行、最终未达预期 |
| 改善趋势 | 与同项目、同目标集合最近七次有效运行比较 |

`unknown` 不会冒充成功或失败。窗口截断的任务不进入效能分母。趋势只表示观察差异，不声明因果关系。

每条用户消息必须被任务覆盖或显式排除。澄清、执行和返工先记录 evidence-linked
interaction event（证据关联交互事件），计数再由 Validator 推导。条件验收使用结构化
acceptance criteria（验收条件），不能只靠自由文本声称成功。

## 兼容保留的 Node 开发入口

下列 Node 命令仅用于现有实现的回归兼容；新项目使用上面的 `sdd-frl` 工作区入口。

- Node.js 20 或更高版本
- Codex CLI；本机验证版本为 `0.145.0`
- 已登录的 Codex 账户

```powershell
npm install
npm test
npm run validate:examples
npm run probe
```

## 旧版集中式配置（兼容保留）

复制 `failure-review.config.example.json` 为 `failure-review.config.json`，然后设置：

| 字段 | 含义 |
|---|---|
| `project_bindings` | 项目根目录、marker、显式会话和本项目可用的 `improvement_target_ids` |
| `improvement_targets` | Skill、AGENTS.md、提示词、脚本或模板的全局定义 |
| `models` | 三个模型阶段的实际模型与推理强度 |
| `privacy.content_mode` | 是否执行常见密钥脱敏 |

例：

```json
{
  "project_bindings": [
    {
      "project_id": "my-project",
      "roots": ["."],
      "marker_file": "failure-review.project.json",
      "conversation_ids": [],
      "improvement_target_ids": ["project-agents", "project-skill"]
    }
  ],
  "improvement_targets": [
    { "id": "project-agents", "type": "agents", "path": "../AGENTS.md" },
    { "id": "project-skill", "type": "skill", "path": "../my-skill/SKILL.md" }
  ]
}
```

多项目配置必须为每个项目绑定目标 ID，防止读取其他项目的改进载体。单项目旧配置仍兼容 `target_skill_allowlist`。

## 旧版集中式运行（兼容保留）

时间窗口采用半开区间 `[window_start, window_end)`：

```powershell
node src/cli.js run `
  --config failure-review.config.json `
  --project-id failure-review-loop `
  --window-start 2026-07-24T00:00:00+08:00 `
  --window-end 2026-07-25T00:00:00+08:00 `
  --timezone Asia/Shanghai
```

可选的 `--target-skill C:\path\to\SKILL.md` 只能从当前项目绑定的 Skill 目标中进一步缩小范围，不能扩大允许清单。

失败重试使用原参数并加 `--run-id <原 run_id>`。如果改进目标内容已经变化，必须开始新运行，不能把不同目标版本混入同一 run。

独立校验：

```powershell
node src/cli.js validate --kind evidence --file runs\<run_id>\evidence.json --run runs\<run_id>\run.json
node src/cli.js validate --kind findings --file runs\<run_id>\findings.json --run runs\<run_id>\run.json --evidence runs\<run_id>\evidence.json
node src/cli.js validate --kind metrics --file runs\<run_id>\metrics.json --run runs\<run_id>\run.json --findings runs\<run_id>\findings.json
node src/cli.js validate --kind trend --file runs\<run_id>\trend.json --run runs\<run_id>\run.json --metrics runs\<run_id>\metrics.json --baseline-metrics baseline-metrics.json
```

`baseline-metrics.json` 是 `trend.json` 中 `baseline_run_ids` 对应的 metrics JSON 数组。
趋势校验必须提供它，Validator 会重新计算完整趋势，不能只检查字段形状。

## 运行结果

| 状态 | 含义 |
|---|---|
| `COMPLETED_NO_TASKS` | 时间窗口内没有可分析任务 |
| `COMPLETED_WITH_METRICS` | 已生成效能、达成率和趋势，没有达到门槛的问题簇 |
| `COMPLETED_WITH_FINDINGS` | 有高频问题，但未配置目标或没有证据支持的目标位置 |
| `COMPLETED_WITH_PROPOSAL` | 已生成供人工确认的提案 |
| `FAILED_*` | 对应阶段失败，下游停止 |

运行产物默认被 Git 忽略。隐私策略见 `docs/privacy.md`，任务去重与门槛见 `docs/contracts/deduplication.md`。

## 自动化边界

- Optimizer 只生成提案，不修改、提交、合并、发布或部署任何载体。
- 每个 eligible issue cluster 必须得到 `proposed` 或 `no_supported_target` 处置。
- 纯环境问题不会生成载体优化提案。
- 历史运行只有在成功结束、契约身份一致，并且 evidence → findings → metrics 全链路重新校验通过后才会进入趋势。
