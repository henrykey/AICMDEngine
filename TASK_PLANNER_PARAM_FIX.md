# 任务规划器参数传递问题修复

## 问题描述

在测试任务规划器时，发现创建用户的操作失败，错误信息为：
```
Execution Error:
MCP command failed: Invalid parameters for tool 'create_member': 
create_member() missing 2 required positional arguments: 'username' and 'email'
```

即使提示词中明确包含了 `username` 和 `email`，MCP 工具仍然无法识别这些参数。

## 根因分析

问题的根本原因在于**参数结构不匹配**：

1. **LLM 生成的计划结构**（来自 planning_engine.py）：
   ```json
   {
     "params": {
       "body": {
         "username": "fang",
         "email": "fang@Joinkey.com",
         "password": "fang@Joinkey.com"
       },
       "headers": {
         "X-Tenant-ID": 1
       }
     }
   }
   ```

2. **MCP 工具期望的参数结构**（在 membership_mcp.py 中定义）：
   ```python
   {
     "username": "fang",
     "email": "fang@Joinkey.com",
     "password": "fang@Joinkey.com"
   }
   ```

3. **问题链条**：
   - Planning Engine 指示 LLM 将参数分类到 `body`、`query`、`path`、`headers` 等对象中
   - Execution Engine 直接将整个 `params` 对象传递给 MCP
   - MCP 的 `base_server.py` 中的参数过滤器只查找顶层参数
   - 由于真正的参数嵌套在 `body` 对象中，无法被识别

## 解决方案

在 `execution_engine.py` 中添加参数扁平化逻辑：

### 1. 新增 `_flatten_mcp_params` 方法

```python
def _flatten_mcp_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten parameters for MCP tool execution.
    
    The planning engine structures parameters like:
    {
        "body": {"username": "alice", "email": "alice@example.com"},
        "headers": {"X-Tenant-ID": 1},
        "query": {"page": 1},
        "path": {"id": "123"}
    }
    
    MCP tools expect flat parameters like:
    {
        "username": "alice",
        "email": "alice@example.com"
    }
    
    This method extracts parameters from body, query, and path,
    and ignores headers (those are handled separately).
    """
    flattened = {}
    
    # Extract from body (most common for POST/PUT requests)
    if "body" in params and isinstance(params["body"], dict):
        flattened.update(params["body"])
    
    # Extract from query (for GET requests with query params)
    if "query" in params and isinstance(params["query"], dict):
        flattened.update(params["query"])
    
    # Extract from path (for path parameters like {id})
    if "path" in params and isinstance(params["path"], dict):
        flattened.update(params["path"])
    
    # If params doesn't have these keys, it's already flat - use as is
    if not any(k in params for k in ["body", "query", "path", "headers"]):
        flattened = params.copy()
    
    return flattened
```

### 2. 修改 MCP 命令执行逻辑

在 `_execute_step` 方法中调用 MCP 命令时，先扁平化参数：

```python
if mcp_name and tool_name:
    # 使用 MCP 执行命令
    logger.info(f"Executing MCP command: {mcp_name}.{tool_name}")
    
    # Extract and flatten parameters for MCP tools
    mcp_params = self._flatten_mcp_params(resolved_params)
    
    # Add auth_token and tenant_id
    mcp_params["auth_token"] = auth_token
    mcp_params["tenant_id"] = tenant_id
    
    logger.debug(f"MCP params after flattening: {mcp_params}")
    
    result = await self.mcp_registry.execute_command(
        mcp_name=mcp_name,
        tool_name=tool_name,
        **mcp_params
    )
```

## 测试验证

```python
engine = ExecutionEngine(None, None)

# Test: Nested params with body
nested = {
    "body": {
        "username": "fang",
        "email": "fang@Joinkey.com",
        "password": "fang@Joinkey.com"
    }
}
result = engine._flatten_mcp_params(nested)
# 期望输出: {'username': 'fang', 'email': 'fang@Joinkey.com', 'password': 'fang@Joinkey.com'}

# Test: Already flat
flat = {"username": "alice", "email": "alice@example.com"}
result = engine._flatten_mcp_params(flat)
# 期望输出: {'username': 'alice', 'email': 'alice@example.com'}
```

## 影响范围

- ✅ 创建用户操作现在可以正常工作
- ✅ 其他 MCP 工具调用也会受益于参数扁平化
- ✅ 向后兼容：如果参数已经是扁平的，不会受到影响
- ✅ 保持了 headers 的独立处理（通过 auth_token 和 tenant_id）

## 后续建议

虽然这个修复解决了眼前的问题，但长期来看可以考虑以下优化：

1. **统一参数格式**：让 Planning Engine 和 MCP Tools 使用一致的参数结构
2. **多轮对话补齐**：当 LLM 检测到缺少必需参数时，自动进入多轮对话模式
3. **参数验证增强**：在执行前验证所有必需参数是否存在

## 修改文件

- `src/services/execution_engine.py`
  - 添加 `_flatten_mcp_params` 方法
  - 修改 `_execute_step` 方法中的 MCP 调用逻辑
