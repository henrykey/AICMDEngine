# 自然语言任务规划服务 (NL-TPS) - 系统设计规范 v1.0

## 1. 概述

### 1.1. 服务定位

自然语言任务规划服务（Natural Language - Task Planning Service, NL-TPS）是一个独立的、AI驱动的智能中间件。其核心职责是将用户以自然语言描述的**高阶任务目标**，转换为一个由原子命令组成的、结构化的、有序的**可执行计划**。

**本服务自身不执行任何命令**。它扮演“任务规划大脑”的角色，将执行的细节和控制权完全交给调用方。

### 1.2. 核心解决的问题

*   **降低人机交互门槛**：用户无需学习复杂的 API 或命令行语法，只需用自然语言描述其最终目的。
*   **自动化复杂工作流**：将需要多个步骤、存在逻辑依赖的复杂任务，自动化地编排成机器可执行的序列。
*   **解耦意图与执行**：将“用户想做什么”（意图）与“系统该怎么做”（执行）彻底分离，使上层业务逻辑和底层命令执行可以独立演进。

### 1.3. 设计原则

*   **单一职责**：专注于“规划”，不参与“执行”。
*   **无状态服务**：核心处理逻辑是无状态的，便于水平扩展。会话状态由调用方管理或通过外部缓存实现。
*   **声明式命令**：通过外部注册的命令集（如 OpenAPI 规范）作为规划的“知识库”。
*   **AI 驱动**：深度利用大型语言模型（LLM）的语义理解、逻辑推理和任务分解能力。

## 2. 系统架构

```
                               +----------------------------------+
                               |      调用方 (Client Application)     |
                               | (e.g., CLI, Web UI, Sync Script) |
                               |                                  |
                               |   +--------------------------+   |
                               |   |     计划执行器 (Plan      |   |
                               |   |       Executor)          |   |
                               |   +--------------------------+   |
                               +-----------------+----------------+
                                                 |
                                     (1) POST /v1/tasks
                                     { "goal": "..." }
                                                 |
                                                 v
+------------------------------------------------------------------------------------+
|                                                                                    |
|                           自然语言任务规划服务 (NL-TPS)                                |
|                                                                                    |
|    +----------------+      +---------------------+      +-----------------------+    |
|    |                |----->|                     |----->|                       |    |
|    |   API 层      |<-----|    任务规划引擎      |<-----|    命令知识库加载器     |    |
|    | (RESTful API)  |      |  (Task Planning Engine) |      | (Command Knowledge Loader)|    |
|    |                |      |                     |      |           ^           |    |
|    +----------------+      +----------+----------+      +-----------|-----------+    |
|                                       |                               |              |
|              (3) 生成并发送 Prompt      |                               | (2) 加载命令集   |
|                                       v                               |              |
|                               +-----------------+            +--------------------+ |
|                               |   AI 模型客户端  |            |   数据库 (MongoDB)   | |
|                               +-----------------+            +--------------------+ |
|                                       |                                            |
|                                       v                                            |
|                              +-----------------+                                   |
|                              |   大型语言模型   |                                   |
|                              |      (LLM)      |                                   |
|                              +-----------------+                                   |
|                                       ^                                            |
|                                       | (4) 返回结构化计划 (JSON)                      |
|                                       |                                            |
|    +----------------------------------+----------------------------------+          |
|    |                                                                    |          |
|    | <-------------------- (5) 返回 Plan_Ready 响应 -------------------- |          |
|    |                                                                    |          |
|    +--------------------------------------------------------------------+          |
|                                                                                    |
+------------------------------------------------------------------------------------+
```

**工作流程:**

1.  **接收任务**: 调用方将用户的自然语言目标（如 "在研发部加入一个叫张三的新员工"）通过 `POST /v1/tasks` 发送给 NL-TPS。
2.  **加载知识**: 任务规划引擎根据请求上下文（如租户ID），从 MongoDB 加载相关的命令集（如 `membership` API 的所有命令定义）。
3.  **生成 Prompt**: 引擎将用户目标和加载的命令集组合成一个精心设计的 Prompt，发送给 LLM。
4.  **AI 规划**: LLM 根据 Prompt 指示，将任务分解成一个包含步骤、参数和依赖关系的 JSON 计划。
5.  **返回计划**: NL-TPS 将 AI 返回的计划封装成 `plan_ready` 响应，返回给调用方。调用方的“计划执行器”负责解析并执行这个计划。

## 3. 数据模型 (MongoDB)

采用两个集合来存储和管理命令。

### 3.1. `command_sets` 集合

存储命令集的元信息，用于组织和隔离。

**Schema:**

```json
{
  "_id": "ObjectId",      // 主键
  "name": "String",         // 命令集名称，需唯一，如 "membership-api-v2.4"
  "description": "String",  // 命令集描述
  "tenantId": "String",     // 所属租户ID，用于多租户隔离
  "sourceType": "String",   // 来源类型, 如 "openapi", "manual"
  "sourceUri": "String",    // 来源地址, 如 OpenAPI 文件的 URL
  "version": "String",      // 版本号
  "createdAt": "Date",
  "updatedAt": "Date"
}
```

### 3.2. `commands` 集合

存储具体的原子命令定义。

**Schema:**

```json
{
  "_id": "ObjectId",          // 主键
  "commandSetId": "ObjectId", // 外键，关联到 command_sets._id
  "tenantId": "String",         // 冗余租户ID，便于查询
  "command": "String",          // 命令唯一标识, 推荐使用 "METHOD /path/template", 如 "POST /v2/members/{id}/roles"
  "summary": "String",          // 命令摘要/一句话描述，如 "给成员分配角色"
  "description": "String",      // 详细描述
  "tags": ["String"],           // 分类标签，如 ["Members", "Roles"]
  "parameters": [               // 参数定义
    {
      "name": "String",         // 参数名, 如 "id", "status"
      "in": "String",           // 参数位置, "path", "query", "header", "body"
      "description": "String",  // 参数的自然语言描述
      "required": "Boolean",
      "schema": {               // 参数的类型和约束 (JSON Schema)
        "type": "String",       // "string", "integer", "boolean", "object", "array"
        "enum": ["String"],
        "properties": {}        // 对于 object 类型
      }
    }
  ],
  "examples": ["String"],       // 更多自然语言示例，用于增强AI理解
  "createdAt": "Date",
  "updatedAt": "Date"
}
```

## 4. AI Prompt 核心设计

Prompt 是驱动 AI 进行正确规划的关键。它必须教会 AI 如何思考。

**模板结构:**

```text
# ROLE
You are an expert AI Task Planner. Your goal is to convert a user's high-level objective into a precise, step-by-step execution plan based on a given set of available commands. You must think step-by-step and identify dependencies.

# COMMANDS
Here are the available commands you can use. Each command is an API endpoint.

${command_definitions_json}

# TASK
User's objective: "${user_goal}"

# INSTRUCTIONS
1.  **Decomposition**: Break down the user's objective into a sequence of logical steps.
2.  **Command Mapping**: For each step, find the most appropriate command from the available COMMANDS.
3.  **Parameter Extraction**: Extract all necessary parameters for each command from the user's objective.
4.  **Dependency Identification**: If a step requires information from a previous step's result (e.g., using a newly created member's ID), you MUST specify this dependency using JSONPath syntax (e.g., "$.steps[0].response.body.id").
5.  **Existence Check**: If the user's objective implies operating on an existing entity (e.g., "in the 'R&D' department"), your plan should first include a step to search for that entity's ID (e.g., using a GET command with a filter).
6.  **Output Format**: Respond ONLY with a valid JSON object adhering to the following schema. Do not add any explanations outside the JSON structure.

# OUTPUT_SCHEMA
{
  "confidence": "A score from 0.0 to 1.0 indicating your confidence in the generated plan.",
  "plan": [
    {
      "step": "Integer, starting from 1.",
      "description": "A brief, human-readable description of what this step does.",
      "command": "The unique identifier of the command to be executed (e.g., 'POST /v2/members').",
      "params": {
        "pathParams": { "key": "value or JSONPath expression" },
        "queryParams": { "key": "value or JSONPath expression" },
        "body": { "key": "value or JSONPath expression" }
      }
    }
  ],
  "question": "If the user's objective is ambiguous or missing critical information to create a complete plan, ask a clarifying question here. Otherwise, this should be null."
}

# RESPONSE
```

## 5. REST API 规范

**Base Path:** `/v1`

### 5.1. 命令集管理

*   `POST /command-sets`: 创建一个新的命令集。
*   `GET /command-sets`: 查询命令集列表。
*   `POST /command-sets/{setId}/commands`: 在指定命令集中注册一个新命令。
*   `GET /command-sets/{setId}/commands`: 查询指定命令集下的所有命令。
*   `DELETE /command-sets/{setId}`: 删除一个命令集及其所有命令。

### 5.2. 任务规划

这是服务的核心端点。

`POST /tasks`

**Request Body:**

```json
{
  "goal": "String", // 必需，用户的自然语言任务目标
  "context": {      // 可选，提供执行上下文
    "tenantId": "String",
    "commandSetNames": ["String"], // 限定在此命令集范围内规划
    "userId": "String"
  }
}
```

**Success Response (200 OK): `plan_ready`**

```json
{
  "type": "plan_ready",
  "confidence": 0.95,
  "plan": [
    {
      "step": 1,
      "description": "首先，查找名为'研发部'的组织的ID",
      "command": "GET /v2/orgs",
      "params": {
        "queryParams": { "keyword": "研发部" }
      }
    },
    {
      "step": 2,
      "description": "然后，创建名为'张三'的新成员",
      "command": "POST /v2/members",
      "params": {
        "body": {
          "username": "zhangsan",
          "fullName": "张三",
          "email": "zhangsan@example.com"
        }
      }
    },
    {
      "step": 3,
      "description": "最后，将新成员关联到'研发部'",
      "command": "POST /v2/members/{id}/orgs",
      "params": {
        "pathParams": {
          "id": "$.steps[1].response.body.id" // 依赖第2步创建的成员ID
        },
        "body": {
          "org_id": "$.steps[0].response.body.data[0].id" // 依赖第1步查到的组织ID
        }
      }
    }
  ]
}
```

**Success Response (200 OK): `clarification_needed`**

```json
{
  "type": "clarification_needed",
  "confidence": 0.4,
  "question": "您是指哪个'研发部'？我们系统中有'上海研发部'和'北京研发部'。"
}
```

**Error Response (4xx/5xx):**

```json
{
  "error_code": "NO_COMMAND_SET_FOUND",
  "error_message": "未找到与租户 'tenant-123' 关联的命令集。"
}
```

## 6. 安全与运维

*   **认证/授权**: 服务本身应受 API Gateway 保护，通过 JWT 或 API Key 进行认证。服务内部通过请求上下文中的 `tenantId` 实现多租户数据隔离。
*   **输入验证**: 对所有输入进行严格验证，特别是 `goal` 字段，防止 Prompt 注入攻击。
*   **速率限制**: 对每个租户或用户进行速率限制，防止滥用昂贵的 AI 调用。
*   **日志与监控**: 记录每个规划请求的元数据（耗时、AI成本、置信度、是否成功），但不记录敏感的业务数据。监控 AI 接口的延迟和错误率。