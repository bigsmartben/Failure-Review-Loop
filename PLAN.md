# Failure Review Loop 实施基线

## 1. 最终目标

通过项目对话识别重复澄清、重复执行和最终未达用户预期的高频模式，以更少轮次、更少执行尝试和更少返工提高用户目标达成率。

review（复盘）、问题分类和改进载体提案都是手段，不是最终结果。

北极星结果：

| 结果 | 口径 |
|---|---|
| 达成率 | `achieved ÷ (achieved + not_achieved)` |
| 结果覆盖率 | `(achieved + not_achieved) ÷ 全部任务` |
| 沟通效能 | 每任务轮次、澄清和重复澄清的平均值与中位数 |
| 执行效能 | 每任务执行尝试和返工的平均值与中位数 |

`unknown` 单独报告，不算成功或失败。

## 2. 流程

```text
定时任务
  ↓
锁定项目、时间窗口、项目目标集合及内容哈希
  ↓
Collector → evidence.json
  ↓
Problem Analyst → findings.json
  ↓
确定性 Metrics → metrics.json
  ↓
确定性 Trend → trend.json
  ↓
同一具体问题是否跨至少三个任务复现？
  ├─ 否 → 指标报告
  └─ 是
      ↓
是否配置项目允许的改进载体？
  ├─ 否 → 高频问题报告
  └─ 是 → Optimizer → proposal.json
```

三个模型阶段严格串行；Metrics 和 Trend 使用普通代码计算，不交给模型。

## 3. 阶段职责

| 阶段 | 单一职责 | 输出 |
|---|---|---|
| Collector | 无损保存角色、顺序、工具关联和窗口边界 | `evidence.json` |
| Problem Analyst | 划分任务、判定三态结果、记录交互成本、形成问题簇 | `findings.json` |
| Metrics | 从已校验 findings 确定性计算当期指标 | `metrics.json` |
| Trend | 与最近七次可比运行确定性比较 | `trend.json` |
| Optimizer | 为每个合格问题簇生成提案或无支持目标处置 | `proposal.json` |

任一阶段不得改写上游产物。Optimizer 不得修改任何改进载体。

## 4. 证据与任务

### 4.1 Evidence

每条证据至少包含：

```text
evidence_id
conversation_id
project_id
timestamp
actor
sequence
event_type
call_id
source_location
content_or_reference
content_hash
collection_status
duplicate_of
```

Collector 同时保存每个 conversation 在窗口前后是否还有事件，但不复制窗口外内容。

### 4.2 Task episode

一个任务片段对应一个可区分的用户目标。同一目标的补充、纠正和返工仍属于原任务。

每条规范 user message 必须被一个任务覆盖，或进入 `excluded_evidence` 并说明稳定原因；
不得通过遗漏失败任务提高达成率。

结果三态：

- `achieved`：用户明确认可或全部验收条件得到证据验证；
- `not_achieved`：用户明确否定、放弃，或结果被证明违反预期；
- `unknown`：静默结束、窗口截断或证据不足。

截断任务必须为 `unknown`，且不进入效能分母。

交互计数：

- `turn_count`：user 和 assistant message 数；
- `clarification_count`：为继续任务索取必要信息；
- `repeated_clarification_count`：重复询问已有信息；
- `execution_attempt_count`：一次面向用户目标的完整交付尝试，不等于工具调用数；
- `rework_count`：交付后因纠正、拒绝或验收失败而重新执行。

除 `turn_count` 外，以上计数不由 Analyst 直接决定。Analyst 先生成带 evidence 引用的
`clarification` 或 `execution_attempt` interaction event，再由 Validator 推导计数。

条件验收使用结构化 `acceptance_criteria`。只有全部条件为 `passed` 才能使用
`verified_acceptance_criteria`；至少一个条件为 `failed` 才能使用
`verified_expectation_mismatch`。

## 5. 高频问题门槛

首版问题模式：

| 模式 | 含义 | severity |
|---|---|---:|
| `repeated_clarification` | 重复询问已提供信息 | 重复澄清次数 |
| `repeated_execution` | 一次任务需要多次交付尝试 | 执行尝试次数减一 |
| `unmet_expectation` | 任务最终未达预期 | 1 |

现有八种类别只表示根因，不作为聚类键。

问题簇身份：

```text
pattern + issue_signature + root_cause_category
```

正式门槛：

> 注册表中的同一问题簇在至少三个不同任务片段中出现，且根因不是纯环境问题。

未注册签名标记为 `candidate`，可以报告，但在注册或归一化前不能触发 Optimizer。

| 场景 | 高频实例数 |
|---|---:|
| 一个任务重复询问五次 | 1，severity 5 |
| 三个任务各出现同一具体问题 | 3，达到门槛 |
| 三个不同 workflow gap | 三个不同问题簇，均未达到门槛 |
| 同一事件出现在日志和用户引用 | 1 |

## 6. 指标与趋势

`metrics.json` 由代码计算：

- 任务总数和三态数量；
- 达成率和结果覆盖率；
- 五项交互计数的样本、总数、平均值、中位数和值分布；
- 三种问题模式的任务发生率。

`trend.json`：

- 只读取同项目、同 `improvement_target_ids`、同契约身份的最近七次完整合法运行；
- 历史 run 必须成功结束，evidence、findings 和 metrics 必须重新通过完整校验；
- 当前或历史有效任务少于三个时返回 `insufficient_data`；
- 展示指标差值和目标集合内容是否变化；
- 固定声明 `observational_only`，不得把相关性写成因果性。

历史旧结构运行保留；缺少合法 `metrics.json` 时不参与趋势。

## 7. 改进载体

全局 `improvement_targets` 支持：

```text
skill
agents
prompt
script
template
```

每个 `project_bindings[]` 通过 `improvement_target_ids` 选择本项目允许读取的载体。多项目配置缺少该绑定时必须停止，防止跨项目读取。

Optimizer 对每个 eligible cluster 必须给出：

- `proposed`：选择一个允许目标，给出最小修改、预期指标方向和回归测试；
- `no_supported_target`：证据不能支持允许目标或位置，不生成猜测性提案。

提案只供人工确认，不自动修改、提交、合并、发布或部署。

## 8. 状态

成功状态：

```text
COMPLETED_NO_TASKS
COMPLETED_WITH_METRICS
COMPLETED_WITH_FINDINGS
COMPLETED_WITH_PROPOSAL
```

失败状态按 Collector、Evidence、Analyst、Findings、Metrics、Trend、Optimizer 和 Proposal 阶段区分。失败会停止下游，并保留已经校验成功的产物。

## 9. 完成定义

只有同时满足以下条件，改造才算完成：

1. evidence 保留角色、顺序、工具关联和窗口边界。
2. findings 能表达任务目标、三态结果、交互成本、问题实例和问题簇。
3. 同一任务多次重复不会膨胀高频实例数。
4. 三个不同任务的相同具体问题才能通过门槛。
5. metrics 和 trend 由普通代码确定性生成并通过 Schema 校验。
6. 报告首先回答达成率、效能和主要浪费位置。
7. 项目只能读取自身绑定的改进载体。
8. 每个合格问题簇有明确 disposition。
9. Optimizer 不能修改任何载体。
10. 正常、门槛、未知、趋势、越界、失败和重试路径均有自动化测试。

## 10. 已确认边界

- 契约继续使用 `schema_version: "1.0.0"`。
- 使用 `contract_revision` 和 `contract_bundle_hash` 区分实际契约身份。
- 旧结构不提供转换，且不进入新趋势。
- 趋势默认最近七次运行，最小样本为三个任务。
- 运行产物默认不提交 Git，不自动删除。
- Scheduled 仍由 ChatGPT 桌面端创建。
