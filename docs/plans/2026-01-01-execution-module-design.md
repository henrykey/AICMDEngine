# 执行模块设计文档

**创建日期**: 2026-01-01
**版本**: 1.0
**状态**: 设计阶段

---

## 1. 概述

### 1.1 目标

为 NL-TPS (自然语言任务规划服务) 增加执行能力，使其不仅能够规划任务，还能执行生成的计划。

### 1.2 设计原则

- **手动回滚**：记录执行状态，提供回滚 API，由管理员决定是否回滚
- **简化 JSONPath**：只支持 `$.steps[N].response.body.*` 格式的依赖解析
- **超时控制**：支持全局超时和每步超时
- **审计集成**：遵循 Membership 审计事件格式，直接写入 MongoDB
- **认证透传**：调用方传递 JWT token，执行器透传给下游 API

---

## 2. 架构设计

### 2.1 整体架构

执行模块作为 NL-TPS 服务的一部分，通过新的路由前缀 `/v1/executions` 暴露 API。

**核心组件**：

1. **ExecutionRouter** (`src/routers/executions.py`)
   - 提供 REST API 端点
   - 处理请求验证

2. **ExecutionEngine** (`src/services/execution_engine.py`)
   - 核心执行逻辑
   - 步骤编排和状态管理

3. **HTTPClient** (`src/services/http_client.py`)
   - HTTP 请求封装
   - 认证处理

4. **ExecutionRepository** (`src/services/execution_repository.py`)
   - MongoDB 交互
   - 审计日志写入

**数据流**：
```
Client → POST /v1/executions
       → ExecutionRouter
       → ExecutionEngine
       → HTTPClient (调用下游 API)
       → ExecutionRepository (保存结果)
       → 返回执行结果
```

### 2.2 部署方式

**选择 B**: 同一个 FastAPI 服务，不同路由前缀

- `/v1/planning/*` - 规划相关
- `/v1/executions/*` - 执行相关

---

## 3. 数据模型

### 3.1 ExecutionRecord（执行记录）

```python
class ExecutionRecord(BaseModel):
    id: str  # ObjectId
    tenant_id: int
    plan_id: str  # 关联到原始计划
    status: str  # running, completed, failed, partial_failed, rollback
    total_steps: int
    completed_steps: int
    failed_steps: int
    global_timeout: int  # 秒
    started_at: datetime
    completed_at: Optional[datetime]
    created_by: str  # user_id
    error_message: Optional[str]
```

### 3.2 StepExecution（步骤执行记录）

```python
class StepExecution(BaseModel):
    id: str  # ObjectId
    execution_id: str  # 关联到 ExecutionRecord
    step_number: int
    command: str  # 如 "POST /users"
    description: str
    status: str  # pending, running, success, failed, rollback
    timeout: int  # 秒
    request_data: dict  # 实际发送的请求
    response_data: Optional[dict]  # API 响应
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    rollback_command: Optional[str]  # 撤销命令
    rollback_status: Optional[str]  # pending, success, failed, skipped
```

### 3.3 MongoDB 集合

- `executions` - 执行记录
- `step_executions` - 步骤执行记录

---

## 4. API 接口

### 4.1 执行计划

```http
POST /v1/executions
Content-Type: application/json
Authorization: Bearer <token>

Request Body:
{
  "plan": [
    {
      "step": 1,
      "command": "POST /users",
      "description": "创建用户",
      "params": {
        "headers": {"X-Tenant-ID": 1},
        "body": {"username": "alice", "email": "alice@example.com"}
      }
    }
  ],
  "global_timeout": 60,
  "tenant_id": 1
}

Response (202 Accepted):
{
  "execution_id": "507f1f77bcf86cd799439011",
  "status": "running",
  "total_steps": 3,
  "started_at": "2026-01-01T10:00:00Z"
}
```

### 4.2 查询执行状态

```http
GET /v1/executions/{id}
Authorization: Bearer <token>

Response (200 OK):
{
  "execution_id": "507f1f77bcf86cd799439011",
  "status": "completed",
  "total_steps": 3,
  "completed_steps": 3,
  "failed_steps": 0,
  "started_at": "2026-01-01T10:00:00Z",
  "completed_at": "2026-01-01T10:00:05Z",
  "steps": [
    {
      "step": 1,
      "command": "POST /users",
      "status": "success",
      "response": {
        "body": {"id": "user_123", "username": "alice"}
      }
    }
  ]
}
```

### 4.3 手动回滚

```http
POST /v1/executions/{id}/rollback
Content-Type: application/json
Authorization: Bearer <token>

Request Body:
{
  "rollback_from_step": 2  # 从第 2 步开始回滚（含第 2 步）
}

Response (200 OK):
{
  "status": "rollback",
  "rolled_back_steps": 2,
  "message": "Successfully rolled back steps 2 and 1"
}
```

---

## 5. 核心流程

### 5.1 执行流程

```python
async def execute_plan(plan, global_timeout, auth_token, tenant_id):
    # 1. 初始化
    execution = ExecutionRecord(
        tenant_id=tenant_id,
        status="running",
        global_timeout=global_timeout
    )
    await db["executions"].insert_one(execution)

    # 2. 顺序执行步骤
    try:
        async with asyncio.timeout(global_timeout):
            for i, step in enumerate(plan):
                # 创建步骤记录
                step_exec = StepExecution(
                    execution_id=execution.id,
                    step_number=i,
                    status="running"
                )

                # 解析 JSONPath 引用
                resolved_params = resolve_references(
                    step.params,
                    step_responses
                )

                # 执行 HTTP 请求
                response = await http_client.execute(
                    command=step.command,
                    params=resolved_params,
                    auth_token=auth_token,
                    tenant_id=tenant_id
                )

                # 记录成功
                step_exec.status = "success"
                step_exec.response_data = response
                await db["step_executions"].insert_one(step_exec)

    except asyncio.TimeoutError:
        execution.status = "timeout"
    except Exception as e:
        execution.status = "partial_failed"
        execution.error_message = str(e)

    # 3. 更新执行状态
    execution.completed_at = datetime.utcnow()
    await db["executions"].update_one(
        {"_id": execution.id},
        {"$set": execution}
    )
```

### 5.2 JSONPath 解析

**支持格式**：`$.steps[N].response.body.*`

**实现**：
```python
def resolve_references(params: dict, step_responses: list) -> dict:
    """
    解析参数中的 JSONPath 引用

    Example:
        $.steps[0].response.body.id → step_responses[0]['response']['body']['id']
    """
    import re

    def resolve_value(value):
        if isinstance(value, str) and value.startswith("$.steps["):
            match = re.match(
                r'\$\.steps\[(\d+)\]\.response\.body\.(.+)',
                value
            )
            if match:
                step_num = int(match.group(1))
                path = match.group(2)
                step_response = step_responses[step_num]
                # 获取嵌套值
                return get_nested_value(
                    step_response,
                    f"response.body.{path}"
                )
        return value

    return recursively_resolve_dict(params, resolve_value)
```

### 5.3 回滚流程

```python
async def rollback_execution(execution_id: str, from_step: int):
    # 1. 获取执行记录
    execution = await db["executions"].find_one({"_id": ObjectId(execution_id)})
    steps = await db["step_executions"].find({
        "execution_id": execution_id,
        "step_number": {"$gte": from_step}
    }).to_list(None)

    # 2. 筛选成功的步骤
    steps_to_rollback = [
        s for s in steps
        if s["status"] == "success"
    ]

    # 3. 反向执行回滚
    for step in reversed(steps_to_rollback):
        if step.get("rollback_command"):
            # 执行撤销命令
            await execute_rollback(step)

            # 更新回滚状态
            await db["step_executions"].update_one(
                {"_id": step["_id"]},
                {"$set": {"rollback_status": "success"}}
            )
        else:
            # 没有撤销命令，跳过
            await db["step_executions"].update_one(
                {"_id": step["_id"]},
                {"$set": {"rollback_status": "skipped"}}
            )

    # 4. 更新执行状态
    await db["executions"].update_one(
        {"_id": ObjectId(execution_id)},
        {"$set": {"status": "rollback"}}
    )
```

---

## 6. HTTP 客户端

### 6.1 实现

```python
import httpx
from typing import Dict, Any

class HTTPClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def execute(
        self,
        command: str,
        params: Dict[str, Any],
        auth_token: str,
        tenant_id: int,
        timeout: int = 30
    ):
        """
        执行 HTTP 请求

        Args:
            command: API 命令，如 "POST /users"
            params: 请求参数
            auth_token: JWT token
            tenant_id: 租户 ID
            timeout: 超时时间（秒）
        """
        # 解析命令
        method, path = self._parse_command(command)

        # 构建请求头
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "X-Tenant-ID": str(tenant_id),
            "Content-Type": "application/json"
        }

        # 构建请求参数
        request_params = self._build_request_params(params)

        # 发送请求
        response = await self.client.request(
            method=method,
            url=self._get_full_url(path),
            headers=headers,
            timeout=timeout,
            **request_params
        )

        # 处理响应
        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.json()
            )

        return response.json()

    def _parse_command(self, command: str):
        """解析命令字符串"""
        parts = command.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid command format: {command}")
        return parts[0], parts[1]

    def _build_request_params(self, params: dict):
        """构建请求参数"""
        request_params = {}

        if "headers" in params:
            request_params["headers"] = params["headers"]
        if "query" in params:
            request_params["params"] = params["query"]
        if "path" in params:
            # 替换路径参数
            path = params["path"]
        if "body" in params:
            request_params["json"] = params["body"]

        return request_params
```

---

## 7. 审计日志

### 7.1 格式遵循 Membership 审计事件

```python
async def write_audit_log(
    db: AsyncIOMotorDatabase,
    tenant_id: int,
    category: str,
    action: str,
    resource: str,
    subject: str,
    payload: dict
):
    """写入审计日志到 MongoDB"""
    await db["events"].insert_one({
        "tenant_id": tenant_id,
        "category": category,
        "action": action,
        "resource": resource,
        "subject": subject,
        "payload_masked": mask_sensitive_data(payload),
        "occurred_at": datetime.utcnow()
    })
```

### 7.2 记录的事件

1. **计划开始执行**
   - category: "task_execution"
   - action: "plan_started"
   - resource: "plan_{plan_id}"

2. **步骤执行完成**
   - category: "task_execution"
   - action: "step_completed"
   - resource: "{command}"

3. **计划执行失败**
   - category: "task_execution"
   - action: "plan_failed"
   - resource: "plan_{plan_id}"

4. **回滚操作**
   - category: "task_execution"
   - action: "rollback"
   - resource: "plan_{plan_id}"

---

## 8. 数据模型扩展

### 8.1 Command 模型扩展

需要为 Command 添加回滚相关字段：

```python
class Command(BaseModel):
    # ... 现有字段 ...

    # 新增字段
    rollback_command: Optional[str] = None  # 撤销命令，如 "DELETE /users/{id}"
    timeout: int = Field(default=30, alias="timeout")  # 超时时间（秒）
```

---

## 9. 文件结构

```
src/
├── routers/
│   └── executions.py          # 执行相关路由
├── services/
│   ├── execution_engine.py    # 执行引擎
│   ├── http_client.py         # HTTP 客户端
│   └── execution_repository.py # 执行数据访问层
├── models/
│   └── execution.py           # 执行相关数据模型
```

---

## 10. 下一步

设计已完成，准备进入实施阶段。

实施步骤：
1. 创建数据模型
2. 实现 HTTP 客户端
3. 实现执行引擎核心逻辑
4. 实现回滚逻辑
5. 创建 API 路由
6. 编写测试
7. 文档更新

预计工作量：2-3 天
