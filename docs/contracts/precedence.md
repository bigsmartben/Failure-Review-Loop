# 契约优先级与版本契约

## 权威顺序

发生冲突时，按照以下顺序处理，不允许用当前实现反向改写上层契约：

1. 本目录中的领域契约（domain contract）定义业务语义、身份和失败条件；
2. JSON Schema 定义产物结构；
3. `src/validation.js` 实现跨产物确定性校验；
4. Prompt 只负责让阶段 Agent 生成契约要求的候选产物；
5. Orchestrator 和其他实现代码执行已经定义的流程；
6. 测试证明实现满足契约，但测试通过不能覆盖或修改契约含义。

当领域语义无法被确定性验证时，产物必须保存判断依据、evidence 引用和未知项，不能把模型判断伪装成确定性事实。

## 当前契约身份

- `schema_version`：`1.0.0`，保留现有产品兼容标识；
- `contract_revision`：`2026-07-24.contract-first.1`；
- `contract_bundle_hash`：由 `src/contract.js` 对领域契约、签名注册表、Schema 和阶段 Prompt 的路径及内容计算。

每个运行和运行产物必须携带相同的契约身份。历史运行只有在契约身份完全一致、成功结束且所有上游产物重新通过校验时，才能进入趋势基线。

修改契约包内任何文件都必须产生新的 `contract_bundle_hash`。发生不兼容语义变化时还必须更新 `contract_revision`。
