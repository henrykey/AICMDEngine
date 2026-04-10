# Membership MCP 任务型工具建设方案

日期：2026-04-09  
状态：Proposed  
范围：Membership MCP / Command Set / Planner / Executor

## 1. 背景

当前 Membership MCP 主要暴露的是单个 API 对应的基础工具，例如：

- `list_members`
- `get_member`
- `create_member`
- `list_roles`

这类工具适合底层调用，但不适合直接承接自然语言任务。用户的真实问题通常是：

- “admin 的详细信息是什么？”
- “王维宏有哪些访问权？”
- “把某成员加到某组织并赋予某角色”

这类任务本质上不是一次 API 调用，而是一段组合流程。当前系统的主要问题是：

1. Planner 容易只生成“查列表 + 查详情”两步，漏掉中间的 ID 解析步骤。
2. LLM 在自然语言里会说“我会获取 ID”，但 plan 中没有真正的可执行动作。
3. 权限查询没有按统一的 `subject_type / subject_id / resource_id` 模型来抽象。
4. Member / Org / Role / Resource 的查找、创建、关联、授权，目前缺少稳定的任务型封装。

因此需要在 Membership MCP 上构建一层“任务型工具”，将 command set 中的原子 API 组合成适合自然语言规划的高层能力。

## 2. 设计目标

### 2.1 总体目标

将 Membership MCP 从“单接口工具集”升级为“任务型工具集”，使 planner 可以优先选用这些高层工具解决自然语言任务。

### 2.2 设计原则

1. 工具面向任务，不直接面向底层 API。
2. 工具内部允许组合多个 command set API。
3. LLM 主要负责理解自然语言和挑选工具。
4. 工具自身负责处理中间依赖，例如 ID 查找、层级展开、主体权限汇总。
5. `member / org / role` 的基础权限机制统一建模为 `subject permission`。
6. `member` 的最终有效权限单独建模，因为它需要叠加：
   - member 自身权限
   - org 权限
   - 上级 org 权限
   - role 权限

## 3. 权限模型抽象

根据当前数据库设计，权限记录统一存储在 `permission` 表中。核心字段为：

- `subject_type`
- `subject_id`
- `resource_id`
- `grant_type`
- `rwx_mask`
- `active`

这意味着：

1. `member / org / role` 本身获得权限的机制完全一致。
2. 差别只在于 `subject_type` 和 `subject_id`。
3. `resource` 是权限作用对象，不是独立的权限来源。
4. `member` 的最终访问权，需要在自身权限之外，额外叠加：
   - 所属 `role` 的权限
   - 所属 `org` 的权限
   - 上级 `org` 链的权限

因此工具设计分为两层：

### 3.1 通用主体权限层

适用于 `member / org / role`：

- 查询主体自身权限
- 给主体授权
- 给主体撤权

### 3.2 成员有效权限层

仅适用于 `member`：

- 汇总 member 自身权限
- 汇总 role 权限
- 汇总 org 和上级 org 权限
- 合并得到最终有效访问权

## 4. 工具分组

Membership MCP 任务型工具分为四组：

1. 获取信息类
2. 创建类
3. 授权类
4. 关联类

## 5. 现有工具复用与更新矩阵

当前 Membership MCP 已有 21 个工具，不应重复新建已有能力。后续工作应分为两类：

1. 更新现有工具，使其具备任务型语义
2. 只补真正缺失的工具

### 5.1 当前已存在工具

当前已存在的核心工具包括：

- `list_members`
- `get_member`
- `get_member_id`
- `create_member`
- `update_member`
- `delete_member`
- `update_member_password`
- `list_roles`
- `create_role`
- `assign_role`
- `list_orgs`
- `get_org`
- `create_org`
- `update_org`
- `delete_org`
- `assign_member_to_org`
- `get_member_orgs`
- `remove_member_from_org`
- `get_org_hierarchy`

### 5.1.1 全量工具审查矩阵

所有现有工具都需要先审查一遍，再决定是直接复用、升级还是维持现状。

| 工具 | 当前定位 | 结论 | 处理建议 |
| --- | --- | --- | --- |
| `list_members` | 基础列表 | 需升级 | 保留完整数据，增强 lookup 语义，避免仅展示前 5 条摘要 |
| `get_member` | 已知 ID 查详情 | 需升级 | 支持 `member_id` 或 `query`，内部自动先 resolve ID |
| `get_member_id` | 成员 ID 解析 | 需升级 | 统一成稳定 lookup 能力，返回 `unique/not_found/multiple` |
| `create_member` | 基础创建 | 基本合格 | 可复用，后续视需要补返回结构和可选上下文 |
| `update_member` | 基础更新 | 待复核 | 先保留，后续看是否需要支持 `query` 定位 |
| `delete_member` | 基础删除 | 待复核 | 高风险操作，暂不作为第一阶段重点 |
| `update_member_password` | 成员改密 | 基本合格 | 可复用，后续修正文档/参数命名一致性 |
| `list_roles` | 基础列表 | 需升级 | 为 `lookup_role` 提供稳定基础数据 |
| `create_role` | 基础创建 | 基本合格 | 可复用，后续视需要补 org 查询支持 |
| `assign_role` | 成员赋角色 | 需升级 | 升级成 `assign_member_role` 语义，支持 `member_query/role_query` |
| `list_orgs` | 基础列表 | 需升级 | 升级为 org lookup 基础工具 |
| `get_org` | 已知 ID 查详情 | 需升级 | 支持 `org_id` 或 `query` |
| `create_org` | 基础创建 | 基本合格 | 可复用，后续视需要补 parent lookup |
| `update_org` | 基础更新 | 待复核 | 先保留，后续看是否需要支持 `query` 定位 |
| `delete_org` | 基础删除/归档 | 待复核 | 高风险操作，暂不作为第一阶段重点 |
| `assign_member_to_org` | 成员入组织 | 基本合格但建议升级 | 后续支持 `member_query/org_query` |
| `get_member_orgs` | 查成员所属组织 | 基本合格 | 可复用，是 member effective permissions 的组成部分 |
| `remove_member_from_org` | 成员移出组织 | 基本合格 | 可复用，后续视需要支持 `query` |
| `get_org_hierarchy` | 查组织层级 | 基本合格 | 可复用，是 member effective permissions 的组成部分 |
| `submit_audit_event` | 审计写入 | 合格 | 与任务型 membership 操作无冲突，维持现状 |
| `submit_audit_events_batch` | 批量审计写入 | 合格 | 与任务型 membership 操作无冲突，维持现状 |

结论：

1. 需要优先升级的现有工具共有 6 个：
   - `list_members`
   - `get_member`
   - `get_member_id`
   - `assign_role`
   - `list_orgs`
   - `get_org`
2. 基本可直接复用的工具共有 8 个：
   - `create_member`
   - `update_member_password`
   - `create_role`
   - `create_org`
   - `assign_member_to_org`
   - `get_member_orgs`
   - `remove_member_from_org`
   - `get_org_hierarchy`
3. 待复核或暂缓的工具共有 5 个：
   - `update_member`
   - `delete_member`
   - `update_org`
   - `delete_org`
   - `list_roles`
4. 审计类工具 2 个，可维持现状。

### 5.2 第一阶段：优先更新的现有工具

第一阶段不追求大量新增工具，先把现有工具升级到可稳定承接自然语言任务。

#### 1. `get_member_id`（升级为稳定 lookup 能力）

用途：根据用户名、姓名、邮箱等线索定位成员。

输入：

- `query`
- `match_fields?`
- `include_inactive?`

输出：

- `status: unique | not_found | multiple`
- `member_id`
- `matched_member`
- `candidates`

内部 API：

- `GET /v2/members`

现状：

- 已存在

需要更新：

- 统一返回 `status: unique | not_found | multiple`
- 返回 `member_id`、`matched_member`、`candidates`
- planner 明确优先使用它，不再“口头说会获取 ID”

#### 2. `list_members`（升级为 lookup 基础数据工具）

用途：获取完整成员集合，供 lookup 和后续步骤消费。

现状：

- 已存在
- 当前更偏展示工具，`content` 只显示前 5 个成员摘要

需要更新：

- 保留完整结构化 `data`
- 支持 lookup 场景，不让摘要文本掩盖完整数据
- 默认 `limit` 和返回语义更适合后续步骤消费

#### 3. `get_member`（升级为 `get_member_profile` 语义）

用途：获取成员详细信息。

现状：

- 已存在
- 当前只适合“已知 member_id”的详情查询

需要更新：

- 支持 `member_id` 或 `query`
- 若输入 `query`，内部自动先调用 `get_member_id`
- 返回更完整的 profile 结构

#### 4. `assign_role`（升级为 `assign_member_role` 语义）

用途：让成员具备某角色。

现状：

- 已存在
- 当前更接近底层 API 包装

需要更新：

- 支持 `member_query`
- 支持 `role_query`
- 内部自动解析 member / role ID
- 返回结构化 assignment 结果

#### 5. `list_orgs`（升级为 org lookup 基础工具）

用途：根据名称、编码等线索定位组织。

输入：

- `query`
- `match_fields?`

输出：

- `status`
- `org_id`
- `matched_org`
- `candidates`

内部 API：

- `GET /v2/orgs`

现状：

- 已存在

需要更新：

- 支持稳定名称匹配
- 返回 `unique/not_found/multiple`
- 为 `get_org`、`create_org`、`assign_member_to_org` 提供统一 org 定位能力

#### 6. `get_org`（升级为 `get_org_profile` 语义）

用途：获取组织详情。

现状：

- 已存在

需要更新：

- 支持 `org_id` 或 `query`
- 若输入 `query`，内部先 lookup org
- 返回更适合 planner/执行器继续消费的结构

### 5.3 第二阶段：真正缺失、需要新增的工具

在以上现有工具更新完成后，再补真正缺失的工具。

#### 7. `lookup_role`

用途：根据角色名、编码等线索定位角色。

输入：

- `query`
- `match_fields?`

输出：

- `status`
- `role_id`
- `matched_role`
- `candidates`

内部 API：

- `GET /v2/roles`

现状：

- 缺失稳定 lookup 工具

#### 8. `lookup_resource`

用途：根据 resource 名称、编码、host、application 线索定位资源。

输入：

- `query`
- `application?`
- `match_fields?`

输出：

- `status`
- `resource_id`
- `matched_resource`
- `candidates`

内部 API：

- `GET /v2/resources`

现状：

- 缺失

#### 9. `get_subject_permissions`

用途：查询某个主体自身被授予的权限，不含继承。

输入：

- `subject_type: member | org | role`
- `subject_id` 或 `query`

输出：

- `subject`
- `permissions`

内部 API：

- `GET /v2/permissions` 或等价权限查询接口
- 必要时先调用 `lookup_member / lookup_org / lookup_role`

现状：

- 缺失

#### 10. `get_member_effective_permissions`

用途：计算成员最终有效访问权。

输入：

- `member_id` 或 `query`

输出：

- `member`
- `direct_permissions`
- `role_permissions`
- `org_permissions`
- `effective_permissions`

内部流程：

1. 定位 member
2. 获取 member 所属 roles
3. 获取 member 所属 orgs
4. 展开上级 org 链
5. 收集所有 subject：
   - member
   - role
   - org
   - parent org
6. 查询这些 subject 的权限
7. 合并输出

内部 API：

- `GET /v2/members`
- `GET /v2/members/{id}/roles`
- `GET /v2/members/{id}/orgs`
- `GET /v2/orgs/{id}/hierarchy`
- 权限查询接口

现状：

- 缺失

#### 11. `create_resource`

用途：创建资源或应用资源。

输入：

- `name`
- `code?`
- `application?`
- `host?`
- `type?`

输出：

- `resource`

内部 API：

- `POST /v2/resources`

现状：

- 如 membership MCP 中无资源创建能力，则新增

### 5.4 现有工具中可直接复用的部分

以下工具当前可直接复用，后续只需在返回结构上做小调整或保持不动：

- `create_member`
- `create_role`
- `create_org`
- `assign_member_to_org`
- `remove_member_from_org`
- `get_member_orgs`
- `get_org_hierarchy`

## 6. 后续第二批工具

在第一阶段更新和第二阶段补缺完成后，再补以下工具。

### 6.1 授权类

- `grant_subject_permissions`
- `revoke_subject_permissions`

输入：

- `subject_type`
- `subject_id` 或 `query`
- `resource_id` 或 `resource_query`
- `rwx_mask` 或动作集合

### 6.2 创建/结构类扩展

- `create_sub_org`
- `create_org_role`
- `create_application_resource`

### 6.3 关联/状态类扩展

- `remove_member_role`
- `move_member_to_org`
- `suspend_member`
- `activate_member`

### 6.4 判定类

- `check_member_resource_access`

用途：判断某成员对某个 resource/host 是否具备访问权。

## 7. 工具与 Command Set 的关系

这些工具不直接替代 command set 中的 API。

两者关系如下：

1. Command Set 中的 API 是原子能力。
2. Membership MCP 任务型工具是组合能力。
3. 每个任务型工具内部通过组合 command set API 完成具体流程。
4. Planner 应优先选择任务型工具，而不是手写多步 API 计划。

示例：

### 问题

“显示成员 admin 的详细信息”

### 旧做法

1. `GET /v2/members`
2. `GET /v2/members/{id}`

问题：中间缺少 ID 解析步骤。

### 新做法

1. `MCP.membership.lookup_member`
2. `MCP.membership.get_member_profile`

或内部展开为：

1. `GET /v2/members`
2. 解析 `admin -> member_id`
3. `GET /v2/members/{id}`

## 8. 规划器适配要求

为了让 LLM 稳定挑选这些工具，Planner 需要同步调整：

1. 将新工具描述同步到 DocIntel。
2. Prompt 中明确：
   - 优先使用任务型 MCP 工具
   - 如果用户只给名称，不给 ID，优先选择 `lookup_*`
   - 不允许只在自然语言里说“我会获取 ID”，必须在 plan 中写成显式步骤
3. 对 member/org/role/resource 查询类任务，优先召回：
   - `lookup_*`
   - `get_*`
   - `assign_*`
   - `grant_*`

## 9. 执行器适配要求

执行器需要支持以下能力：

1. 接收任务型 MCP 工具返回的结构化数据。
2. 支持后续步骤使用工具返回的：
   - `member_id`
   - `org_id`
   - `role_id`
   - `resource_id`
3. 对缺失中间依赖的 plan 做前置校验。
4. 不再允许“无 ID 直接调用详情/权限接口”的假计划进入执行阶段。

## 10. DocIntel 同步策略

所有新工具需要同步到 DocIntel，至少包含：

1. 工具名称
2. 工具描述
3. 输入参数
4. 输出结果
5. 典型使用场景
6. few-shot 示例

建议同步两类文档：

### 10.1 Tool 文档

例如：

- `MCP.membership.lookup_member`
- `MCP.membership.get_member_effective_permissions`

### 10.2 Plan Example 文档

例如：

- “显示 admin 的详细信息”
- “王维宏有哪些访问权”
- “把 kehongwei 加入研发部并赋予管理员角色”

## 11. 实施顺序

### 当前进度（2026-04-09）

- `Phase 1` 已完成代码实现：
  - `get_member_id`
  - `list_members`
  - `get_member`
  - `assign_role`
  - `list_orgs`
  - `get_org`
- `Phase 2` 已完成代码实现：
  - `lookup_role`
  - `lookup_resource`
  - `get_subject_permissions`
  - `get_member_effective_permissions`
  - `create_resource`
- 当前 Membership MCP 工具总数：`26`
- 当前已知限制：
  - 公开 command set 中没有组织自身权限查询 API，因此 `get_subject_permissions(subject_type=org)` 和 `get_member_effective_permissions` 会显式返回 limitation，而不会伪造 org 权限结果。

### Phase 1

优先更新现有 6 个工具：

1. `get_member_id`
2. `list_members`
3. `get_member`
4. `assign_role`
5. `list_orgs`
6. `get_org`

### Phase 2

补真正缺失的 5 个工具：

1. `lookup_role`
2. `lookup_resource`
3. `get_subject_permissions`
4. `get_member_effective_permissions`
5. `create_resource`

### Phase 3

补后续扩展工具：

- 授权类
- 状态类
- 结构类扩展
- 判定类

### Phase 4

将成功案例与工具描述同步到 DocIntel，反哺规划器。

## 12. 验收标准

Phase 1 和 Phase 2 完成后，至少应满足以下能力：

1. “显示 admin 的详细信息”
   - 不再缺 ID 解析步骤

2. “王维宏有哪些访问权”
   - 能正确汇总：
     - member 自身权限
     - role 权限
     - org 权限
     - 上级 org 权限

3. “把 kehongwei 加到研发部并赋予管理员角色”
   - 可使用任务型工具生成稳定 plan

4. Planner 优先选择任务型工具，而不是散乱底层 API

5. 调试视图中，plan 应出现真实的任务型工具步骤，而不是自然语言幻想步骤
6. membership MCP 的升级优先基于已有工具，不重复引入语义重叠的新工具

## 13. 结论

Membership MCP 的下一阶段建设重点，不再是继续增加单个 API 工具，而是优先升级已有工具，再补少量真正缺失的任务型工具。

优先顺序是：

1. 先把已有工具变成稳定的任务型能力
2. 再补 `lookup_role / lookup_resource / get_subject_permissions / get_member_effective_permissions / create_resource`
3. 最后再扩展授权类、状态类和访问判定类工具

这是让 Membership MCP 从“可调用”走向“可用于稳定完成自然语言任务”的关键一步。
