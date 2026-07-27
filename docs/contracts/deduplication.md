# 证据、任务与问题聚类契约

本文件受 `precedence.md` 管理。契约身份由 `schema_version`、`contract_revision` 和
`contract_bundle_hash` 共同确定。

## 证据哈希（evidence content hash）

`content_hash` 是以下字段规范 JSON 的 SHA-256：

```text
conversation_id
+ timestamp
+ actor
+ sequence
+ event_type
+ call_id
+ source_location
+ content_or_reference
```

格式为 `sha256:<64 个小写十六进制字符>`。同一事件从不同来源出现时保留多条 evidence，重复项通过 `duplicate_of` 直接指向规范记录；不允许引用链。

## 任务片段（task episode）

一个任务片段对应一个可区分的用户目标。用户对同一目标的补充、纠正和返工仍属于原任务；实质不同的新目标建立新任务。

每个任务保存：

- 对话和 sequence 范围；
- 用户目标与预期结果；
- `achieved`、`not_achieved` 或 `unknown`；
- 澄清、重复澄清、执行尝试和返工计数；
- 事实、推断、未知项及 evidence 引用。

窗口截断的任务必须标记为 `unknown`，不进入效能统计分母。

### 任务覆盖（task coverage）

每条规范 user message evidence 必须满足且只满足以下一种状态：

- 被一个 task episode 覆盖；
- 写入根级 `excluded_evidence`，并使用稳定 `reason_code` 解释为什么它不是用户任务。

不允许既未分配也未排除。该覆盖门用于防止遗漏失败任务后虚高达成率。

### 窗口依据（boundary basis）

`context_status` 必须同时保存 `context_basis` 和 `boundary_evidence_ids`：

- `complete` → `fully_observed`，不得声明边界证据；
- `left_truncated` → `left_boundary_continuation`，会话必须存在窗口前事件；
- `right_truncated` → `right_boundary_continuation`，会话必须存在窗口后事件；
- `both_truncated` → `both_boundary_continuation`，两侧都必须存在窗口外事件。

截断判断仍包含语义分析，但其依据必须显式、可回溯。

### 验收条件（acceptance criteria）

任务可以记录结构化 `acceptance_criteria`。每项保存稳定 ID、描述、状态和验证 evidence：

- `verified_acceptance_criteria`：至少一项条件，全部为 `passed`；
- `verified_expectation_mismatch`：至少一项条件为 `failed`；
- `insufficient_evidence`：不得出现 `failed`，也不得声明结果 evidence；
- 明确用户认可或否定：结果 evidence 必须包含 user message。

所有通过或失败的条件都必须引用验证 evidence。Validator 从条件状态和引用推导结果是否合法。

### 交互事件（interaction event）

澄清和执行成本先记录事件，再由 Validator 推导计数：

- `clarification`：使用 `repeated: true|false`；
- `execution_attempt`：使用 `rework: true|false`；
- 每个事件必须引用任务范围内 evidence；
- 多个读取、编辑、测试和工具结果可以共同引用为一个执行尝试。

`counts` 是事件的派生摘要，不是独立事实。除 `turn_count` 从消息计算外，其余计数必须与
`interaction_events` 精确一致。

## 问题实例指纹（problem fingerprint）

`fingerprint` 是以下字段规范 JSON 的 SHA-256：

```text
task_episode_id
+ conversation_id
+ pattern
+ issue_signature
```

因此，同一任务对同一具体问题最多贡献一个实例。任务内重复五次通过 `severity: 5` 表达，不生成五个高频样本。

例：

```text
task_1 连续五次重复询问已给出的目录
→ 1 个 repeated_clarification 实例
→ severity = 5
→ 高频实例数 = 1
```

## 问题簇（issue cluster）

同一组字段形成一个问题簇：

```text
pattern
+ issue_signature
+ root_cause_category
```

问题簇 ID 是以上字段规范 JSON 的 SHA-256 前 16 位，格式为 `ic_<16 hex>`。

只有满足以下条件才通过 Optimizer 就绪门：

- 至少三个不同 `task_episode_id`；
- 所有实例具有相同问题模式、具体签名和根因分类；
- 根因不是纯 `environment_issue`；
- 所有任务、实例和证据引用通过确定性校验。
- `issue_signature` 已存在于 `issue-signatures.json` 注册表。

三个不同的 `workflow_gap` 不会因为根因分类相同而被合并。

未注册的新签名使用 `signature_status: candidate`。候选签名可以报告，但在归一化或人工注册前
不得触发 Optimizer。

## 确定性校验

JSON Schema 校验字段形状；`src/validation.js` 负责跨产物规则：

- evidence 角色、顺序、工具调用关联和来源记录一一对应；
- 任务结果与结果依据一致；
- 截断任务不能声明已达成或未达成；
- severity 与任务计数一致；
- 一个任务不能重复贡献同一问题实例；
- cluster 的实例、任务、severity 和 evidence 精确匹配；
- eligible cluster 必须由三个独立任务推导；
- proposal 必须覆盖每个 eligible cluster 的处置结果。
- 每条规范 user message 都被任务覆盖或显式排除；
- 交互事件与计数精确一致；
- 验收条件、结果依据和结果 evidence 一致；
- 截断状态具有合法的会话边界和 evidence 依据；
- 只有注册签名可以通过高频门槛；
- 趋势历史运行必须在相同契约身份下重新通过完整上游校验。
