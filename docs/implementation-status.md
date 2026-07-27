# 实施状态（2026-07-27）

## 已落地

| 能力 | 状态 | 说明 |
|---|---|---|
| 对话证据 | 完成 | 角色、顺序、事件类型、可选 call ID、窗口边界和来源一致性校验 |
| 任务级分析 | 完成 | task episode、用户消息覆盖门、结构化验收条件、边界依据 |
| 交互成本 | 完成 | evidence-linked interaction event，五项计数由 Validator 推导 |
| 高频问题 | 完成 | 三种模式、签名注册表、跨三个独立任务门槛；candidate 不触发 |
| 确定性指标 | 完成 | 达成率、覆盖率、效能分布和模式发生率 |
| 历史趋势 | 完成 | 最近七次同范围同契约运行、完整上游复验、确定性差值复算 |
| 契约身份 | 完成 | `contract_revision`、契约包哈希和明确权威顺序 |
| 多载体安全 | 完成 | 项目级目标绑定、精确路径校验、内容哈希和防修改检查 |
| 改进提案 | 完成 | 按问题簇提案、预期指标方向、结构化无支持目标处置 |
| 报告 | 完成 | 达成率 → 效能 → 趋势 → issue-ready 问题小节 → 提案；Python/JS 共享 golden contract |
| Codex App 宿主 | 完成 | Scheduled Task 负责定时与原生子代理编排 |
| 原生 Agent | 完成 | 项目级 TOML 固定模型、推理强度和只读边界 |
| Handoff 状态机 | 完成 | `prepare → continue → finalize`，Schema 与稳定阻塞码 |
| 采集诊断 | 完成 | `analysis_root` 绑定、显式 ID 覆盖、窗口前后计数、空结果原因与 source probe |
| 配置迁移 | 完成 | `config.json.models` 一次性迁移至 `.codex/agents/*.toml` |

验证基线：`uv run pytest` 与 `npm test` 必须全部通过；具体数量以当前版本为准。

## 模型映射

| 阶段 | 模型 | 推理强度 |
|---|---|---|
| Analyst | `gpt-5.6-sol` | `high` |
| Optimizer | `gpt-5.6-sol` | `medium` |

Collector、Metrics 与 Trend 由 Python 确定性执行，不调用模型。模型配置的唯一所有者是
`.codex/agents/sdd-frl-*.toml`。

## 生产启用前仍需配置

- 实际项目根目录、marker 或 conversation ID；
- 每个项目的 `improvement_target_ids`；
- 真实载体路径及稳定 ID；
- 在 Codex App 确认本地项目、每天 09:00 和生产时区；
- 保留期限和项目专用脱敏规则。

历史旧结构运行保留，但不会进入新趋势。首次生产运行后应抽查任务切分、显式排除、
验收条件和交互事件是否符合业务预期。
