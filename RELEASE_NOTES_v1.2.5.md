# Release Notes — v1.2.5

**Release Date:** 2026-10-10  
**Repository:** AICMDEngine  
**Changes since:** v1.2.4  
**Paired Membership release:** v2.4-R0.4.0

## Summary

本版本聚焦 PDF2MD Enhanced 的源内容优先处理、计算表审核工具和 Docs/MCP 职责边界。MCP 提供转换、显式对象语义、查询及有界恢复能力；分类、恢复选择、调用预算和后续索引流程由 Membership Docs 控制。源内容在语义或结构化处理失败时仍可保留和审阅。

## PDF2MD Enhanced

- 支持绑定文档、页面及源身份的 PNG 抽取，完善计算表源内容、公式、表格单元格图片和未完成对象的保留与溯源。
- 提供源绑定的计算表处理、显式续处理、分块 OCR/VLM 转录和逐公式语义能力；限制物理请求预算与阶段截止时间，并记录阶段耗时。
- 恢复工具使用调用方明确提供的区域和引擎，校验源哈希与坐标，保留逻辑顺序及来源；恢复失败时保留完整源内容。
- 将通用转换中的自动分类、自动语义补齐和自动恢复编排移回 Docs；通用表格工具不接受模型自行提出的计算业务分类或计算 JSON 作为转换结果。
- 对象语义与表格查询按单次物理调用执行，避免工具内部隐藏重试；移除已失去调用入口的自动编排逻辑和过时测试。
- 完善复杂表格查询、对象语义证据校验、公式编号恢复、数学定界符、表题/图题恢复和图片处理，保留抽取证据与未完成图对象。

## Provider and Transport

- 新增 Plan2 Thinking 控制与安全 Provider 诊断，将共享 Thinking 策略应用于 MCP 请求。
- 修复 MCP WebSocket Router 并发和过期连接映射清理。
- 修复 PDF2MD 镜像所需计算预处理及对象语义模块的打包遗漏。

## Integration and Upgrade

- 本版本与 Membership **v2.4-R0.4.0** 配套。转换不再隐式完成业务分类和语义编排；调用方必须明确安排所需处理，不能继续假定转换响应已完成这些步骤。
- Docs 在保存源内容后补齐必要语义，再完成归一化和索引；未完成语义的源内容仍保留供审阅。计算 JSON 和逐公式语义由调用方显式选择。
- 两端共享转换边界契约 fixture，验证 MCP 输出与 Java 解析及首次处理消费路径。MCP 实现基线为 `3434257`，Membership 实现基线为 `a1b67469`。

## Verification and Limits

- 本轮 PDF2MD 定向离线回归：**943 passed**，使用合成数据和 Provider stub。
- 未计入上述通过范围：远程人工测试脚本 `test_pdf2md_enhanced_mcp.py`；`test_pdf2md_enhanced_http_transport.py` 中已确认的两项既有失败（FastMCP 接口差异及 Dockerfile COPY 断言）。不能据此宣称全仓库测试通过。
- 配套 Membership 本轮定向验证：Docs 327 项、API 18 项、前端 81 项通过，相关 Java 编译及前端构建通过；另有已确认的既有 Java 测试失败未纳入通过范围。
- 真实模型、真实 PDF/Word 端到端、运行时 UI 回读和性能目标尚未验收。此前阶段的部署或健康检查不构成本版本的部署证明。
- 本次仅提交发布文档并创建本地标签；未推送、构建镜像、部署或重启服务。
