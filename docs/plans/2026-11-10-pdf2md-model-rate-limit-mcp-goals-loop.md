# PDF2MD MCP：模型限流错误契约 Goals Loop Plan

日期：2026-11-10

状态：部分实现，待 MCP 侧 agent 继续完成和验证。配套计划：[Membership 侧计划](/Users/kehongwei/workspace/membership/docs/plans/2026-11-10-docintel-model-rate-limit-recovery-goals-loop.md)。

## 目标与职责边界

当逐页抽取中的 OCR 或 VLM 明确遇到临时模型限流时，PDF2MD MCP 为当前页返回可识别的 `error_code=MODEL_RATE_LIMITED`。永久额度不足、认证失败和其他错误不伪装成临时限流，要有明确可区分的错误信息。MCP 执行一次明确请求并返回结果；等待、退避、文档任务、检查点、取消和重新调度由 Membership Docs 负责。

范围为本地 `/Users/kehongwei/workspace/AICMDEngine` 的 PDF2MD MCP 及其测试。不得引入 MCP 内部的无限业务重试、文档生命周期或 Membership 数据库依赖。不要部署、构建容器、调用真实模型、提交或推送。

## 本地基线与已完成部分

- 基线检查时为 `main`、HEAD `ea08c61`；执行前重新核对 checkout、状态和 `AGENTS.md`，保留已有改动。
- 当前未提交修改涉及 `mcp/servers/PDF2MDEnhanced/server.py`、`ocr_clients/openai_compatible_ocr_client.py` 和新增 `tests/test_pdf2md_rate_limit_contract.py`。这些是本任务的部分成果，不应覆盖。
- `process_task_page` 的异常路径可对异常链中的可识别 HTTP 429 返回 `MODEL_RATE_LIMITED`；OCR layout 请求保留异常原因。已知 `insufficient_quota`、`billing_hard_limit_reached` 排除在该判定之外。
- 已运行的离线验证：新增 2 项模拟测试、3 项现有 OCR 相关测试通过。尚未证明 OCR/VLM 全路径、异步重试缓存或与 Membership 的联通；当前代码中页面限流仍经过 `update_page_failed`，其对同页重试和任务状态的影响需验证。

## 对外契约

| 情况 | MCP 页工具结果 | Membership 预期 |
| --- | --- | --- |
| 确认临时模型限流 | 返回 `error_code: MODEL_RATE_LIMITED`，保持任务和页身份；不返回伪成功内容 | 等待并重试同一页 |
| 永久额度不足或认证失败 | 返回与临时限流可区分的明确错误及安全诊断 | 停止并提示，不作无限限流重试 |
| 其他失败 | 按既有错误契约明确返回 | 沿既有失败路径处理 |

对方不得依赖从原始错误正文猜测限流。可可靠取得的 `Retry-After` 是否需要透传，应与 Membership 侧协调并冻结字段；缺失时调用方使用自己的退避策略。不得输出凭证、提示词、原文或未经清理的上游响应。

## Goals Loop

| Goal | 状态 | 任务 | 验收条件 |
| --- | --- | --- | --- |
| P0 基线与契约 | 已部分调查 | 审查 MCP 逐页入口、OCR/VLM 错误及现有部分实现，确认与 Membership 的共同字段 | 错误字段、页/任务身份、临时与永久错误分类均有双方可用的具体样例 |
| P1 真实调用链限流传播 | 部分完成 | 核查 OCR、VLM 和页面识别实际异常如何向 `process_task_page` 传递；明确返回统一错误码 | 用模拟 provider 从实际客户端经页面处理到工具响应验证；限流不能被降级为空结果或伪成功；非限流反例不误判 |
| P2 同页安全重试 | 未完成 | 检查失败状态、异步 `calculation_async` 缓存、旧结果及来源身份；确保调用方可再次请求同页 | 连续限流后同页成功；旧的失败结果不会被无限复用；之前成功的页和身份不改变，异步在途操作不重复执行 |
| P3 非限流错误与安全 | 部分完成 | 扩展永久配额、认证和普通错误覆盖，核查日志和响应 | 不把永久问题归为临时限流；响应/日志不泄露凭证、文档、提示词或模型原始响应 |
| P4 MCP 离线验收与交接 | 未完成 | 增加失败优先契约测试并运行聚焦及相关回归；向 Membership 侧提供实际工具响应样例 | 模拟 provider → MCP 工具结果链通过；样例携带 `MODEL_RATE_LIMITED`；记录已覆盖及未覆盖的模型路径；双方验证前不宣称跨仓库完成 |

## 执行与验证

先为尚未覆盖的 OCR/VLM 和异步重试写失败测试，再做最小源码修改；保留 existing bounded technical retries，不把无限等待引入 MCP。每批源码修改后运行 `codegraph sync`；运行对应 `.venv/bin/python -m pytest -q --no-cov` 离线聚焦测试及相关回归。交接前检查 `git diff --check`、工作树及原有改动。不可启动基础设施、请求真实模型或部署。

## 执行记录

截至 2026-11-10：P1 和 P3 的上述本地实现与测试仅部分完成；P2、P4 未完成。具体改动未提交、未部署。最终跨服务限流自动恢复须由 Membership 侧实现并经双方合成样例验收。
