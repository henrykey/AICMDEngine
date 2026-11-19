# Release Notes — v1.2.9

发布日期：2026-11-19
仓库：AICMDEngine
变更范围：在 v1.2.8 基础上合入此前本地 PDF2MD 提交，合并提交为 `c41f785`。

## 合并来源

- 远端 v1.2.8：`0a3f1f2`，包含 Workflow 所需的结构化目录查询与 Form MCP 能力。
- 本地 `a8e022d`：PDF2MD 模型限流、额度和认证错误处理。
- 本地 `01174c9`：公式语义映射失败的结构化诊断。
- 合并保留双方提交历史，无冲突，无额外业务代码改写。

## PDF2MD 变化

- 分类并传播可识别的模型错误：临时限流 `MODEL_RATE_LIMITED`、永久额度不足 `MODEL_QUOTA_EXHAUSTED`、认证失败 `MODEL_AUTH_FAILED`，避免将这些错误作为普通降级结果吞掉。
- 公式目标无法唯一匹配原始布局时，返回 `FORMULA_MAPPING_FAILED`，提供 `reason`、`target_index` 和 `model_calls=0`。缺失标识、重复标识、找不到源布局等原因可区分。
- MCP 执行受限工具操作；文档生命周期、等待退避和业务重试仍由 Membership 管理。本次不宣称跨服务自动恢复已验收。

## 保留的 Workflow MCP 能力

- `membership.lookup_org`、`membership.lookup_role`：结构化结果、中英文消息，以及完整目录分页检查。
- `form_mcp.find_forms`：在调用者身份与租户范围内只读查询已有表单。
- `form_mcp.suggest_form`：不调用模型，复用 Membership 的只读 `proposals/check` 生成和校验表单结构，不保存或发布。
- 新版 Form MCP 替换旧工具接口；旧工具调用方须按 v1.2.8 的接口变化核对。

## 配置与使用前提

- Membership 的 MCP Router 地址与 Router 的 `MEMBERSHIP_SERVICE_URL` 须互相指向正确服务；调用使用有效用户令牌及租户。
- 表单建议的 Membership 校验需要 `workflow.create`、`workflow.update` 或 `*` 权限；目录、表单读取需要相应读取权限。
- Membership 设计助手仍需按租户配置 `workflow.assistant` 模型用途；`suggest_form` 本身不需要独立模型配置。设计 Skill 的发布和激活属于 Membership 租户配置，不由本标签自动完成。

## 验证与限制

- 合并前工作区干净；双方修改文件没有交集，自动合并无冲突。
- 核对合并结果：本地 16 个改动文件、远端 11 个改动文件均与各自来源内容一致；完成最终 diff 审查和 Git 空白检查。
- CodeGraph 状态查询无法打开数据库，未重建索引。
- 按用户要求，本次未运行测试、构建、真实模型调用、部署或服务重启。仓库包含相关测试代码，但不代表本次已执行或通过。
- 真实模型行为、限流后的跨服务恢复、合并版本端到端运行均未验证；v1.2.8 的历史验证记录不能替代本次组合版本验收。
- 提交和标签发布只更新源码版本，不代表现有容器已经更新。
