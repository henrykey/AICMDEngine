# MCP DocIntel 适配指南

## 1. 目的

本指南定义如何改造内部 MCP 与第三方 MCP，使其能够接入 DocIntel 检索链路，并被 planner 以“先检索候选工具，再由 LLM 选择工具并生成 plan”的方式稳定使用。

目标不是把 MCP 当成零散 API 暴露出去，而是把 MCP 工具变成：

- 可被 DocIntel 检索召回的任务能力
- 可被 LLM 理解并选择的语义化工具
- 可被执行器稳定执行的结构化工具

---

## 2. 基本原则

### 2.1 工具不是 API 直译

MCP 工具应优先表达“任务”，而不是简单表达“某个 HTTP 接口”。

例如：

- 好：`get_member_effective_permissions`
- 好：`lookup_member`
- 差：`call_permissions_api`

一个 MCP 工具内部可以组合多个 command set API。

### 2.2 DocIntel 检索的是语义，不只是参数

仅有 `input_schema` 不足以支撑工具召回。  
DocIntel 需要知道：

- 这个工具解决什么问题
- 典型自然语言问题是什么
- 输出能给后续步骤什么关键结果
- 它通常与哪些步骤配合使用

### 2.3 工具注册信息是语义源头

MCP 工具的语义元数据应直接挂在 Tool 注册模型上，而不是维护一套独立文档再人工同步。

推荐做法：

- `Tool` 顶层保留执行元数据
- `Tool` 顶层新增语义元数据
- DocIntel 同步时直接读取 Tool 注册信息生成检索文档

### 2.4 命令集与 MCP 工具共用一套检索机制

不建议单独发明一套“MCP 文档上传系统”。  
应沿用 command set 的 DocIntel 同步机制：

- command set API 作为一类文档
- MCP tools 作为另一类文档
- 通过 `source_type` / `category` / `tags` 区分

---

## 3. 目标工作流

完整链路如下：

1. 用户提出自然语言问题
2. 系统将问题发给 DocIntel
3. DocIntel 返回相关 command set API 与 MCP tool 候选
4. planner 将“用户问题 + 候选工具/命令 + 规划规则”发给 LLM
5. LLM 返回结构化 plan 和用户可读的 plan 描述
6. 执行器执行 plan

对于 MCP 适配来说，核心是让第 3 步能够准确召回正确工具。

---

## 4. Tool 注册模型规范

## 4.1 必填执行字段

每个 Tool 至少包含：

- `name`
- `description`
- `input_schema`
- `handler`

## 4.2 新增语义字段

为接入 DocIntel，每个 Tool 应扩展以下字段：

- `semantic_description`
- `use_cases`
- `natural_language_examples`
- `output_description`
- `tags`

推荐结构：

```python
Tool(
    name="lookup_member",
    description="Resolve a member ID from member details",
    semantic_description="根据用户名、姓名、邮箱等线索解析唯一成员 ID。",
    use_cases=[
        "根据自然语言线索获取成员 ID",
        "为成员详情、权限、组织查询提供 member_id",
    ],
    natural_language_examples=[
        "admin 的成员 ID 是多少？",
        "显示用户 admin 的详细信息",
        "王维宏有哪些访问权？",
    ],
    output_description="返回 status、member_id、matched_member、candidates。",
    tags=["membership", "member", "lookup", "task_tool"],
    input_schema={...},
    handler=self.lookup_member,
)
```

---

## 5. `input_schema` 的职责

`input_schema` 继续只负责描述参数结构：

- 参数名
- 参数类型
- 参数字段说明
- 是否必填

例如：

```json
{
  "type": "object",
  "properties": {
    "page": {
      "type": "integer",
      "description": "Page number (1-indexed)",
      "default": 1
    },
    "limit": {
      "type": "integer",
      "description": "Number of items per page",
      "default": 10
    },
    "search": {
      "type": "string",
      "description": "Search query (optional)"
    }
  }
}
```

不建议把全部语义解释硬塞进 `input_schema`。  
原因是：

- schema 面向执行器和校验器
- 语义说明面向检索器和 LLM
- 两者职责不同

如果历史兼容需要，也可以在 schema 中保留 `x-*` 扩展字段，但不应作为主方案。

---

## 6. DocIntel 文档构建规范

每个 MCP tool 在同步到 DocIntel 时，应被转成一条“可检索命令文档”。

### 6.1 文档字段

建议最少包含：

- `externalId`
- `title`
- `category`
- `content`
- `metadata`

### 6.2 分类建议

MCP 工具与 command set API 一起进入同一套 DocIntel corpus，但需明确区分：

- `source_type`
  - `command`
  - `mcp_tool`

- `category`
  - API: `cmdengine.command.<domain>`
  - MCP: `cmdengine.command.mcp`

- `tags`
  - 如：`membership`, `member`, `lookup`, `task_tool`

### 6.3 检索文本组成

DocIntel 的检索文本应组合以下内容：

- Tool 名称
- Tool 描述
- 语义描述
- use cases
- 自然语言示例
- 参数名
- 参数描述
- 输出说明
- tags

推荐拼接结果类似：

```text
Command: MCP.membership.lookup_member
Source Type: mcp_tool
Source Name: membership
Summary: Resolve a member ID from member details
Description: 根据用户名、姓名、邮箱等线索解析唯一成员 ID。
Tags: membership, member, lookup, task_tool
Examples: admin 的成员 ID 是多少？, 显示用户 admin 的详细信息
Parameter Names: query, members, match_fields
Parameter Descriptions: query: ..., members: ..., Output: 返回 status、member_id、matched_member、candidates
```

---

## 7. MCP 工具设计规范

## 7.1 优先做任务型工具

对于适配 DocIntel 的 MCP，优先提供以下类型工具：

- `lookup_*`
- `get_*`
- `create_*`
- `assign_*`
- `grant_*`
- `check_*`

避免工具只表达底层运输行为。

## 7.2 输入尽量贴近自然语言线索

工具应优先支持：

- `id`
- `query`

例如：

- `member_id` 或 `query`
- `role_id` 或 `query`
- `org_id` 或 `query`

这样 LLM 不需要自己把自然语言完全转成主键。

## 7.3 输出必须适合后续步骤继续消费

工具输出不能只适合“人看”，必须适合“机器继续执行”。

例如 lookup 工具应返回：

```json
{
  "status": "unique",
  "member_id": 1,
  "matched_member": {
    "id": 1,
    "username": "admin",
    "fullName": "System Administrator"
  }
}
```

不应只返回：

```text
Found a likely member
```

## 7.4 显式返回不确定状态

lookup 类工具推荐统一返回：

- `unique`
- `not_found`
- `multiple`

不要把“未能解析”伪装成业务结论。

---

## 8. 第三方 MCP 适配步骤

第三方 MCP 接入 DocIntel 时，建议按以下顺序改造。

### Step 1：审查工具清单

先列出第三方 MCP 已有工具，判断：

- 哪些工具语义清晰，可直接用
- 哪些工具只是低层封装，需要升级
- 哪些关键任务能力缺失，需要补工具

### Step 2：补齐 Tool 语义字段

为每个工具增加：

- `semantic_description`
- `use_cases`
- `natural_language_examples`
- `output_description`
- `tags`

### Step 3：统一输出结构

重点检查：

- lookup 工具是否返回唯一匹配结果
- list 工具是否保留完整结构化数据
- get 工具是否支持 `id/query` 双输入

### Step 4：同步到 DocIntel

复用现有 command set 同步机制，把 MCP tool 转成检索文档。

### Step 5：更新 planner 候选集输入

确保 planner 在构造 prompt 时能同时拿到：

- command set API 候选
- MCP tool 候选

并优先选择任务型工具。

### Step 6：加回归测试

至少覆盖：

- 工具注册
- 工具语义元数据存在
- DocIntel 文档构建结果正确
- planner 能召回关键工具

---

## 9. 对第三方 MCP 的最低改造要求

如果第三方 MCP 无法大改，最低要求如下：

1. 给每个 tool 提供稳定的 `name`
2. 给每个 tool 提供清晰的 `description`
3. 增加至少以下语义字段：
   - `semantic_description`
   - `natural_language_examples`
   - `tags`
4. `input_schema` 必须完整可读
5. 输出至少应有结构化 `data`

如果第三方 MCP 只能满足这五项，也可以先接入 DocIntel。

---

## 10. Planner 配合要求

即使 MCP 工具已同步进 DocIntel，planner 仍需遵循以下规则：

1. 优先选择任务型工具，而不是散乱底层 API
2. 如果工具已经能自动解析 ID，不要再手写多步 API 计划
3. 如果后续步骤依赖 `{id}`，plan 中必须有能产出该 `id` 的前置步骤
4. 用户可见的 `plan_description` 必须和结构化 `plan` 一致

---

## 11. 不适合接入 DocIntel 的工具类型

以下工具不建议优先作为 DocIntel 主召回对象：

- 纯审计写入工具
- 纯内部维护工具
- 缺乏自然语言任务价值的低层工具
- 输出不可结构化消费的工具

这类工具可以保留在 MCP 中，但不应作为主要检索候选。

---

## 12. membership MCP 作为参考实现

Membership MCP 已实现一套参考模式：

- Tool 注册模型扩展了语义字段
- DocIntel 文档构建支持读取这些语义字段
- planner 已能消费这些增强后的 MCP 候选
- 现有工具已按“优先升级现有工具、只补真正缺失的工具”方式演进

可作为其它内部 MCP 和第三方 MCP 的改造样板。

参考代码：

- [tool.py](/Users/kehongwei/workspace/AICMDEngine/src/mcp/tool.py)
- [command_document_builder.py](/Users/kehongwei/workspace/AICMDEngine/src/services/command_document_builder.py)
- [membership_mcp.py](/Users/kehongwei/workspace/AICMDEngine/src/mcp_servers/membership_mcp.py)

---

## 13. 推荐实施顺序

对于任意 MCP，建议按以下顺序推进：

1. 审查现有工具，做合格性分类
2. 补 Tool 语义字段
3. 改 list/get/lookup 三类核心工具
4. 接入 DocIntel 同步
5. 调整 planner 优先召回任务型工具
6. 加回归测试
7. 再继续补复杂任务工具

---

## 14. 一句话总结

MCP 适配 DocIntel 的关键，不是把工具名同步过去，而是把工具改造成“可检索、可理解、可执行的任务能力”，并让工具语义直接绑定在 Tool 注册模型上，再沿用 command set 的同步和检索机制统一进入 planner。
