# Release Notes — v1.2.8

发布日期：2026-11-19
仓库：AICMDEngine
变更范围：`v1.2.7` 至本版本

## Membership MCP

- `lookup_org` 和 `lookup_role` 支持结构化查询结果与中英文消息；目录分页必须完整，读取不完整时返回错误，不将部分结果当作完整结果。

## Form MCP

- `find_forms` 通过现有 MCP Router 只读查询调用人可访问的表单。
- `suggest_form` 不调用模型，输出 Membership 表单结构并复用 Membership 的权威校验；不保存或发布表单。
- 移除原先无法通过 Router 发现或调用的旧工具。身份和租户由现有调用路径传递；本版不修改 MCP Router 或协议。

## 验证与限制

- Workflow 请假场景使用模型替身，在真实浏览器、后端、Router 和流程引擎上验证了相关工具与流程；这不是使用真实模型的完整场景验收。
- 已有 Membership MCP 目录测试的报告注明使用了本机非标准测试垫片。测试结果与限制详见 Membership 仓库中的 `docs/workflow/goals-loop/reports/` 相关报告。
- 本次发布文档工作未重跑完整测试套件，也未构建或部署；标签不代表生产部署完成。
