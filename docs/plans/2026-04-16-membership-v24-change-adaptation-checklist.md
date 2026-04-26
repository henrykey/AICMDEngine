# Membership v2.4 设计/API 变更适配清单

日期：2026-04-16  
状态：Active  
范围：AICMDEngine / Membership MCP / Planner / Executor / DocIntel / UI

## 1. 目的

当 Membership v2.4 的设计规范更新，或 Membership API 新增/修改端点时，AICMDEngine 不能只改某一个位置。

必须沿着以下链路做完整适配：

1. 文档源更新
2. MCP 工具更新
3. Planner / Retriever 适配
4. Executor 兼容
5. UI 展示适配
6. DocIntel 同步
7. 回归验证
8. 运行环境同步

本清单用于后续每次 Membership v2.4 演进时的标准执行流程。

## 2. 单一事实来源

Membership API 变更的主对照源应统一为：

- [membership_v2.4_openapi.yaml](/Users/kehongwei/workspace/AICMDEngine/docs/membership_docs/membership_v2.4_openapi.yaml)

如果仓库中存在其他副本，例如：

- [membership_v2.4_openapi.yaml](/Users/kehongwei/workspace/AICMDEngine/docs/membership_v2.4_openapi.yaml)

则必须明确：

1. 它是废弃副本
2. 或它必须同步更新

否则 planner / 开发者 / 调试人员会基于不同版本做判断，导致工具与 API 脱节。

### 2.1 标准检查脚本

本仓库已经补充半自动检查脚本：

- [check_membership_v24_adaptation.py](/Users/kehongwei/workspace/AICMDEngine/scripts/check_membership_v24_adaptation.py)

标准执行方式：

```bash
python scripts/check_membership_v24_adaptation.py
```

需要连同前端构建一起检查时：

```bash
python scripts/check_membership_v24_adaptation.py --with-build
```

该脚本当前负责检查：

1. 主 OpenAPI 是否存在
2. 旧副本是否仍存在
3. 关键端点是否在主规范和模块化路径中出现
4. MCP 工具是否已覆盖关键端点
5. 工具是否补齐语义元数据
6. 相关 Python 文件是否可编译

脚本应作为每次 Membership v2.4 变更后的第一道回归检查，而不是靠人工逐项比对。

## 3. 变更分类

Membership 变更通常分为四类：

### 3.1 新增端点

例如：

- `/v2/llm/providers`
- `/v2/llm/usage-configs/{purpose}/resolved`

需要判断：

1. 是否需要新增 MCP 工具
2. 是否应该包装成任务型工具，而不是仅暴露原子 API

### 3.2 端点参数变化

例如：

- path 参数变化
- query 参数新增
- request body 字段变更

需要同步修改：

- `input_schema`
- handler 参数签名
- HTTP payload/path/query 组装逻辑

### 3.3 响应结构变化

例如：

- 返回对象变数组
- 字段名变化
- 嵌套结构变化

需要同步修改：

- MCP 工具的 `content` 摘要
- `data` 返回结构
- Executor 引用解析
- UI 展示格式化

### 3.4 语义变化

例如：

- 原本是“直接权限”，现在变成“有效权限”
- 原本只返回 role id，现在返回 role 对象

这类变更必须同步到：

- 工具描述
- Planner prompt
- DocIntel 工具语义文档

## 4. MCP 工具层适配要求

每次 Membership API 更新时，都要先建立受影响工具清单。

需要逐项检查：

1. 是否已有对应工具
2. 该工具是否仍与新 OpenAPI 一致
3. 是否需要从原子工具升级为任务型工具

### 4.1 新增端点时

判断规则：

1. 如果用户会直接以自然语言问到这个能力，优先新增任务型工具。
2. 如果只是内部辅助步骤，可以只加基础工具。
3. 如果是常用 lookup / resolution / management 操作，必须带完整语义描述。

### 4.2 每个工具必须同步的内容

新增或修改 Membership MCP 工具时，至少同步以下内容：

1. `name`
2. `description`
3. `semantic_description`
4. `use_cases`
5. `natural_language_examples`
6. `output_description`
7. `tags`
8. `input_schema`
9. handler 实现

### 4.3 返回结构要求

工具不能只返回“人类可读摘要”，必须保留可供后续步骤消费的结构化 `data`。

尤其对于以下工具：

- lookup 工具
- get details 工具
- relation 工具
- permission 汇总工具

应确保输出中包含可直接复用的字段，例如：

- `member_id`
- `org_id`
- `role_id`
- `resource_id`
- `matched_member`
- `matched_org`
- `matched_role`
- `roles`
- `permissions`

## 5. Planner / Retriever 适配要求

Membership API 变化后，不能只改 MCP 工具，还要改 planner 和检索层。

### 5.1 Retriever

若新增了关键任务型工具，应检查：

- [command_retriever.py](/Users/kehongwei/workspace/AICMDEngine/src/services/command_retriever.py)

是否需要把它补进 membership helper commands。

典型场景：

- `lookup_org`
- `get_member_roles`
- 新增的 LLM provider 管理工具

### 5.2 Planner

需要检查：

- [planning_engine.py](/Users/kehongwei/workspace/AICMDEngine/src/services/planning_engine.py)

重点包括：

1. prompt 中是否提到新工具优先级
2. 是否需要新增 plan 规范
3. 是否需要新增 plan 自动修正规则
4. 是否需要修复中间依赖步骤缺失问题

### 5.3 Direct MCP Executor

需要检查：

- [direct_mcp_executor.py](/Users/kehongwei/workspace/AICMDEngine/src/services/direct_mcp_executor.py)

如果新工具支持自然语言 query 自动补参，则要扩展 fallback 规则。

## 6. Executor 兼容要求

Membership API 返回结构变化时，执行器经常会出问题。

必须检查：

- [execution_engine.py](/Users/kehongwei/workspace/AICMDEngine/src/services/execution_engine.py)
- [execution.py](/Users/kehongwei/workspace/AICMDEngine/src/models/execution.py)

### 6.1 重点检查项

1. `response_data` 是否仍能容纳新的返回类型
2. 前一步结果提取逻辑是否仍正确
3. JSONPath/引用表达式是否仍可解析
4. 是否需要兼容 list / dict / nested object

### 6.2 常见失效模式

1. 工具返回数组，但模型声明成 `Dict`
2. 旧的 JSONPath 仍假设数据在 `data[*].id`
3. 新返回结构变成 `{ matched_member, member_id }`
4. 规划里遗漏 lookup 步骤，但执行器没有拦截

## 7. UI 适配要求

Membership API 和 MCP 工具更新后，必须同步检查前端展示。

涉及位置：

- [ChatPanel.tsx](/Users/kehongwei/workspace/AICMDEngine/plan2/src/components/ChatPanel.tsx)
- [PlannerExecutorPanel.tsx](/Users/kehongwei/workspace/AICMDEngine/plan2/src/components/PlannerExecutorPanel.tsx)
- [ExecutionResultRenderer.tsx](/Users/kehongwei/workspace/AICMDEngine/plan2/src/components/ExecutionResultRenderer.tsx)

### 7.1 必查项

1. 聊天栏摘要是否仍可读
2. 嵌套对象是否被错误显示为 `[Object]`
3. 结果是否需要 Markdown 渲染
4. 角色、组织、权限、provider 等对象是否展开关键字段

### 7.2 展示规则

对于对象值，不应直接显示 `[Object]`，而应优先展示：

- `name`
- `fullName`
- `username`
- `code`
- `id`

对于列表结果，应优先格式化成 Markdown 列表或表格，而不是单行字符串。

## 8. DocIntel 同步要求

新增或修改 MCP 工具后，DocIntel 不会自动获知这些变化。

必须执行一次 MCP 工具同步，使新增工具进入检索库。

相关入口：

- `POST /v1/command-index/sync-mcp-docintel`

如果未同步，会出现：

1. 新工具已在代码中存在
2. 但 cmdengine 检索不到
3. planner 仍按旧工具集合规划

## 9. 回归验证清单

每次 Membership API 更新后，至少执行以下验证：

### 9.1 代码级

1. Python 编译：
   - `python -m py_compile ...`
2. 前端构建：
   - `npm run build`

### 9.2 MCP 工具级

1. 工具是否成功注册
2. `input_schema` 是否正确
3. handler 是否可调用
4. 返回结构是否符合设计

### 9.3 任务级

至少验证以下自然语言任务：

1. 详情类：
   - “显示用户 admin 的详细信息”
2. 角色类：
   - “list all roles user wangwh belong to”
3. 权限类：
   - “王维宏有哪些访问权？”
4. 组织关联类：
   - “把 kehongwei 加入研发部”
5. 新增领域类：
   - “列出所有 LLM providers”
   - “docintel.chat 用哪个 provider？”

## 10. 运行环境同步

当前项目运行容器通常不是源码挂载模式。

因此本地改完后，必须同步到运行环境：

1. 后端文件 `docker cp` 到 `mcp-router-dev`
2. 容器内编译检查
3. 重启 `mcp-router-dev`
4. 前端构建并同步 `plan2-ui-dev`

如果不做这一步，就会出现：

1. 本地代码已更新
2. 容器里仍是旧逻辑
3. 测试结果和代码状态不一致

## 11. 建议执行顺序

建议每次 Membership v2.4 更新都按下面顺序执行：

1. 确认新版 OpenAPI 和设计文档
2. 列出受影响端点
3. 建立 MCP 工具变更清单
4. 修改 MCP 工具注册与 handler
5. 修改 planner / retriever / executor 兼容逻辑
6. 修改前端渲染
7. 更新计划文档
8. 同步 MCP 工具到 DocIntel
9. 编译与任务回归
10. 同步到运行容器

## 12. 结论

Membership v2.4 的设计/API 更新，不是“更新接口定义”这么简单。

在 AICMDEngine 中，它至少影响：

1. OpenAPI 文档源
2. Membership MCP 工具
3. Planner / Retriever
4. Executor
5. UI 展示
6. DocIntel 检索语义
7. 容器运行环境

以后每次 Membership 端点变更，都应以本清单作为标准适配流程执行。
