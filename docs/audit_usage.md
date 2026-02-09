# AICMDEngine 审计日志使用指南

## 快速开始

### 1. 初始化

```python
from src.mcp.audit_integration import SimpleAuditLogger
from src.mcp.registry import get_mcp_registry

# 初始化审计日志记录器
audit_logger = SimpleAuditLogger(get_mcp_registry())
```

### 2. 从 JWT 提取信息

当客户端连接到 AICMDEngine 时，JWT token 包含：

```python
# JWT token 结构
jwt_token = {
    "member_id": 123,      # 会员ID
    "tenant_id": 456,      # 租户ID
    "username": "user123",
    "exp": 1234567890
}

# 提取信息
tenant_id = jwt_token.get('tenant_id')
member_id = jwt_token.get('member_id')
```

### 3. 记录审计日志

#### 场景1：记录工具调用

```python
async def handle_tool_call(jwt_token, tool_name, arguments):
    # 提取 JWT 信息
    tenant_id = jwt_token.get('tenant_id')
    member_id = jwt_token.get('member_id')

    # 执行工具
    try:
        result = await execute_tool(tool_name, arguments)

        # 记录成功
        await audit_logger.log_operation(
            tenant_id=tenant_id,
            member_id=member_id,
            action="MCP_TOOL_CALL_SUCCESS",
            category="API",
            tool_name=tool_name,
            arguments=arguments,
            success=True
        )
        return result

    except Exception as e:
        # 记录失败
        await audit_logger.log_operation(
            tenant_id=tenant_id,
            member_id=member_id,
            action="MCP_TOOL_CALL_ERROR",
            category="API",
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            error_message=str(e)
        )
        raise
```

#### 场景2：记录自定义操作

```python
# 创建文档
await audit_logger.log_operation(
    tenant_id=tenant_id,
    member_id=member_id,
    action="CREATE_DOCUMENT",
    category="SYSTEM",
    metadata={
        "filename": "report.docx",
        "size": 1024,
        "path": "/Documents/report.docx"
    }
)

# 删除文件
await audit_logger.log_operation(
    tenant_id=tenant_id,
    member_id=member_id,
    action="DELETE_FILE",
    category="DATA",
    metadata={"path": "/tmp/file.txt"}
)

# 执行计划
await audit_logger.log_operation(
    tenant_id=tenant_id,
    member_id=member_id,
    action="EXECUTE_PLAN",
    category="WORKFLOW",
    metadata={
        "plan_id": "plan_123",
        "steps": 5,
        "status": "completed"
    }
)
```

## API 参考

### SimpleAuditLogger.log_operation()

```python
async def log_operation(
    tenant_id: int,              # 必需：租户ID（从JWT提取）
    member_id: int,              # 必需：会员ID（从JWT提取）
    action: str,                 # 必需：操作名称
    category: str = "API",       # 可选：分类（API/SYSTEM/AUTH/DATA/WORKFLOW）
    tool_name: str = None,       # 可选：工具名称
    arguments: dict = None,      # 可选：工具参数（会自动脱敏）
    success: bool = True,        # 可选：是否成功
    error_message: str = None,   # 可选：错误信息
    metadata: dict = None        # 可选：额外元数据
)
```

### 常用 Action 名称建议

| 分类 | Action 名称 | 说明 |
|------|-------------|------|
| API | MCP_TOOL_CALL_SUCCESS | 工具调用成功 |
| API | MCP_TOOL_CALL_ERROR | 工具调用失败 |
| API | WEBSOCKET_CONNECT | WebSocket连接 |
| API | WEBSOCKET_DISCONNECT | WebSocket断开 |
| SYSTEM | CREATE_DOCUMENT | 创建文档 |
| SYSTEM | DELETE_FILE | 删除文件 |
| SYSTEM | EXECUTE_PLAN | 执行计划 |
| AUTH | USER_LOGIN | 用户登录 |
| AUTH | USER_LOGOUT | 用户登出 |
| DATA | FILE_UPLOAD | 文件上传 |
| DATA | FILE_DOWNLOAD | 文件下载 |
| WORKFLOW | TASK_START | 任务开始 |
| WORKFLOW | TASK_COMPLETE | 任务完成 |

### Category 分类

- **API**: API 相关操作（工具调用、WebSocket连接等）
- **SYSTEM**: 系统操作（创建文档、执行计划等）
- **AUTH**: 认证相关（登录、登出等）
- **DATA**: 数据操作（文件读写、数据库操作等）
- **WORKFLOW**: 工作流相关（任务执行、流程控制等）

## 完整示例

```python
import asyncio
from src.mcp.audit_integration import SimpleAuditLogger
from src.mcp.registry import get_mcp_registry

async def example_usage():
    # 初始化
    audit_logger = SimpleAuditLogger(get_mcp_registry())

    # 模拟从 JWT 提取的信息
    tenant_id = 456
    member_id = 123

    # 示例1：工具调用成功
    await audit_logger.log_operation(
        tenant_id=tenant_id,
        member_id=member_id,
        action="MCP_TOOL_CALL_SUCCESS",
        category="API",
        tool_name="filesystem.read_file",
        arguments={"path": "/tmp/config.json"}
    )

    # 示例2：工具调用失败
    await audit_logger.log_operation(
        tenant_id=tenant_id,
        member_id=member_id,
        action="MCP_TOOL_CALL_ERROR",
        category="API",
        tool_name="filesystem.read_file",
        arguments={"path": "/nonexistent.txt"},
        success=False,
        error_message="File not found"
    )

    # 示例3：自定义操作
    await audit_logger.log_operation(
        tenant_id=tenant_id,
        member_id=member_id,
        action="EXECUTE_PLAN",
        category="WORKFLOW",
        metadata={
            "plan_id": "plan_123",
            "task_count": 5,
            "duration_ms": 1500
        }
    )

    print("✅ 审计日志记录完成")

# 运行示例
asyncio.run(example_usage())
```

## 注意事项

### 1. 参数脱敏

系统会自动脱敏敏感参数：

```python
# 这个参数会被自动脱敏
arguments = {
    "path": "/tmp/file.txt",
    "password": "secret123"  # → "***REDACTED***"
}

# 记录后
# {"path": "/tmp/file.txt", "password": "***REDACTED***"}
```

**敏感关键词**：`password`, `token`, `secret`, `key`, `credential`, `authorization`

### 2. 错误处理

审计日志记录失败不会影响主业务流程：

```python
try:
    await audit_logger.log_operation(...)
except Exception as e:
    # 审计失败不影响业务
    logger.error(f"Audit log failed: {e}")
```

### 3. 性能考虑

- 审计日志是异步的，不会阻塞主业务
- 建议在关键操作后记录审计
- 避免在循环中频繁记录

## 故障排除

### 问题1：Tool not found: submit_audit_event

**原因**: membership MCP 未注册或版本过旧

**解决**:
```bash
# 检查 membership MCP 是否已更新
# 确保有 submit_audit_event 工具
```

### 问题2：Invalid actor: must provide memberId or systemCode

**原因**: actor 对象格式错误

**解决**:
```python
# ✅ 正确
actor = {"memberId": 123}

# ❌ 错误
actor = {}
```

### 问题3：503 Service Unavailable

**原因**: Audit 服务未启用

**解决**:
- 检查 membership 服务是否运行
- 确认 audit REST API 已部署

## 参考资源

- [Membership Audit REST API 规范](../membership_docs/IMPLEMENTATION_AUDIT_REST_API.md)
- [Audit API 迁移指南](../membership_docs/AUDIT_API_MIGRATION.md)
