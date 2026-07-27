# 可操作问题报告契约

## 职责边界

问题报告（findings report）始终把每个问题簇渲染成可独立复制到 Issue tracker
的 Markdown 小节。Optimizer 提案（optimizer proposal）只在问题簇通过就绪门后生成；
未达到门槛不会降低问题报告的可读性。

## 输入与关联

| 输入 | 关联规则 |
|---|---|
| `issue_clusters[].problem_instance_ids` | 精确关联 `problem_instances[]` |
| `problem_instances[].task_episode_id` | 关联 `task_episodes[]` |
| `issue_clusters[].evidence_ids` | 关联 `evidence.records[]`，只输出 JSON 指针 |
| `optimizer_eligible_cluster_ids` | 决定门槛状态，不决定是否输出问题小节 |

任务数按唯一 `task_episode_id` 计算。同一任务属于多个问题簇时，每个任务实例都要显示
全部关联簇，避免把不同问题模式误读成不同任务。

## 输出

每个问题簇必须包含：人类可读标题、问题描述、预期与实际、任务实例、已验证事实、
推断、未知项、根因与置信度、影响、严重度、证据指针、Optimizer 门槛及建议验收标准。
根因字段一律标为 Analyst 的推断，不能因为置信度高就改写成已验证事实。

## 隐私与边界条件

- 不复制 `evidence.records[].content_or_reference`、原始对话或 `source_location`。
- 证据只显示 `evidence_id` 和 `evidence.json#/records/<index>`。
- 未解析证据显示稳定警告 `EVIDENCE_POINTER_UNRESOLVED`。
- 缺少可理解摘要时显示 `DESCRIPTION_MISSING`；正常管线会先由 Schema 拒绝该产物。
- 问题簇引用不存在的问题实例时，交叉产物校验必须失败，不得静默省略。
- 根因置信度为 `unknown` 时，报告必须明确显示“证据不足，根因尚未确认”。

## 可验证规则

Python 与 JavaScript 报告器必须读取同一个
`fixtures/report/actionable-findings.json`，并与同一个
`fixtures/report/actionable-findings.expected.md` 完全一致。共享 fixture 覆盖单实例簇、
多任务簇、同任务多模式、未知根因、缺失证据和敏感原始内容不泄露。
