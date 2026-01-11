# MCP 快速开始指南

## 5分钟快速集成新MCP

### 第1步：创建MCP服务器类（2分钟）

```python
# src/mcp_servers/github_mcp.py
from src.mcp import BaseMCPServer, Tool, ToolResult
from src.services.http_client import HTTPClient

class GitHubMCPServer(BaseMCPServer):
    def __init__(self, github_token: str):
        super().__init__("github", "1.0")
        self.github_token = github_token
        self.http_client = HTTPClient(base_url="https://api.github.com")
        self._register_tools()

    def _register_tools(self) -> None:
        # 工具1：搜索仓库
        self.register_tool(Tool(
            name="search_repos",
            description="Search GitHub repositories",
            input_schema={
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Search query"},
                    "page": {"type": "integer", "description": "Page number", "default": 1}
                },
                "required": ["q"]
            },
            handler=self.search_repos
        ))

    async def search_repos(self, q: str, page: int = 1, **kwargs) -> ToolResult:
        try:
            response = await self.http_client.execute(
                command="GET /search/repositories",
                params={"query": {"q": q, "page": page}},
                auth_token=self.github_token,
                tenant_id=1  # 占位符，GitHub API不需要tenant
            )
            return ToolResult.success(str(response))
        except Exception as e:
            return ToolResult.error(str(e), error_code="SEARCH_ERROR")
```

### 第2步：注册MCP（1分钟）

```python
# src/main.py
from src.mcp_servers.github_mcp import GitHubMCPServer

@app.on_event("startup")
async def startup_db_client():
    # ... 现有代码 ...

    # Initialize MCP Registry
    mcp_registry = MCPRegistry()

    # 添加这三行
    github_token = os.getenv("GITHUB_TOKEN")
    github_mcp = GitHubMCPServer(github_token)
    mcp_registry.register_mcp(github_mcp)

    # 注册到app
    app.mcp_registry = mcp_registry
```

### 第3步：在任务中使用（2分钟）

```typescript
// 前端：在任务规划中指定MCP命令
const plan = [
    {
        step: 1,
        command: "github.search_repos",  // 格式: mcp_name.tool_name
        description: "Search for repositories",
        params: {
            query: {
                q: "python machine learning"
            }
        }
    }
];

// 发送执行请求
const res = await api.post('/executions/', {
    plan: plan,
    global_timeout: 60
});
```

---

## 常见命令格式

### MCP工具命令
```
格式: {mcp_name}.{tool_name}
示例:
  - membership.list_members
  - github.search_repos
  - your_service.get_item
```

### HTTP直接命令（无需MCP）
```
格式: GET|POST|PUT|DELETE /api/path
示例:
  - GET /v2/orgs
  - POST /v1/items
  - PUT /v1/items/{id}
```

---

## 参数传递

### 查询参数 (Query String)
```json
{
  "params": {
    "query": {
      "page": 1,
      "limit": 10
    }
  }
}
```

### 路径参数 (Path Variables)
```json
{
  "params": {
    "path": {
      "id": "user_123",
      "org": "myorg"
    }
  }
}
```

### 请求体 (Body)
```json
{
  "params": {
    "body": {
      "name": "New Item",
      "description": "Description here"
    }
  }
}
```

---

## 检查MCP状态

### API端点：获取所有MCP
```bash
GET /v1/mcp/servers

Response:
{
  "servers": [
    {
      "name": "membership",
      "status": "running",
      "tools_count": 8,
      "tools": [
        {
          "name": "list_members",
          "description": "List all members",
          "input_schema": {...}
        }
      ]
    }
  ]
}
```

### 检查特定MCP
```bash
GET /v1/mcp/servers/github

Response:
{
  "name": "github",
  "version": "1.0",
  "status": "running",
  "tools_count": 5,
  "metadata": {
    "description": "GitHub API integration",
    "author": "Your Name"
  }
}
```

---

## 问题排查

| 问题 | 原因 | 解决方案 |
|------|------|--------|
| "MCP not found" | MCP未注册 | 检查 `main.py` 中是否调用了 `register_mcp()` |
| "Tool not found" | 工具未注册 | 检查 `_register_tools()` 中的工具名称 |
| 401 Unauthorized | Token过期 | 系统会自动刷新token，检查日志 |
| 504 Timeout | 请求超时 | 增加 `global_timeout` 或检查远程服务 |

---

## 测试MCP

### 使用curl测试
```bash
# 1. 获取可用MCP
curl http://localhost:8000/v1/mcp/servers

# 2. 获取特定MCP的详情
curl http://localhost:8000/v1/mcp/servers/github

# 3. 通过execution API执行MCP命令
curl -X POST http://localhost:8000/v1/executions/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "X-Tenant-ID: 1" \
  -H "Content-Type: application/json" \
  -d '{
    "plan": [
      {
        "step": 1,
        "command": "github.search_repos",
        "params": {
          "query": {
            "q": "python"
          }
        }
      }
    ]
  }'
```

### 查看日志
```bash
# 查看MCP初始化日志
tail -f startup.log | grep "MCP Registry\|Registered MCP"

# 查看执行日志
tail -f startup.log | grep "Executing.*command"
```

---

## 最佳实践

✅ **DO**:
- 在MCP中包装所有第三方API调用
- 使用descriptive的工具名称
- 定义完整的 JSON Schema for input validation
- 实现适当的错误处理

❌ **DON'T**:
- 在工具处理器中硬编码credentials（使用env变量）
- 创建过于复杂的input schema
- 忽略token认证和刷新
- 在同步函数中调用异步操作

---

## 完整示例：集成Slack API

```python
# src/mcp_servers/slack_mcp.py
from src.mcp import BaseMCPServer, Tool, ToolResult
from src.services.http_client import HTTPClient
import os

class SlackMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__("slack", "1.0")
        self.slack_token = os.getenv("SLACK_BOT_TOKEN")
        self.http_client = HTTPClient(base_url="https://slack.com/api")
        self._register_tools()

    def _register_tools(self) -> None:
        # 发送消息工具
        self.register_tool(Tool(
            name="send_message",
            description="Send a message to a Slack channel",
            input_schema={
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "Channel ID or name"
                    },
                    "text": {
                        "type": "string",
                        "description": "Message text"
                    }
                },
                "required": ["channel", "text"]
            },
            handler=self.send_message
        ))

        # 获取用户列表
        self.register_tool(Tool(
            name="list_users",
            description="List all users in the Slack workspace",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max number of users to return",
                        "default": 100
                    }
                }
            },
            handler=self.list_users
        ))

    async def send_message(self, channel: str, text: str, **kwargs) -> ToolResult:
        try:
            response = await self.http_client.execute(
                command="POST /chat.postMessage",
                params={
                    "body": {
                        "channel": channel,
                        "text": text
                    }
                },
                auth_token=self.slack_token,
                tenant_id=1
            )
            return ToolResult.success(str(response))
        except Exception as e:
            return ToolResult.error(str(e), error_code="SEND_MESSAGE_ERROR")

    async def list_users(self, limit: int = 100, **kwargs) -> ToolResult:
        try:
            response = await self.http_client.execute(
                command="GET /users.list",
                params={
                    "query": {"limit": limit}
                },
                auth_token=self.slack_token,
                tenant_id=1
            )
            return ToolResult.success(str(response))
        except Exception as e:
            return ToolResult.error(str(e), error_code="LIST_USERS_ERROR")
```

然后在 `main.py` 中注册：

```python
slack_mcp = SlackMCPServer()
mcp_registry.register_mcp(slack_mcp)
```

在任务中使用：

```json
{
  "plan": [
    {
      "step": 1,
      "command": "slack.list_users",
      "params": {"query": {"limit": 50}}
    },
    {
      "step": 2,
      "command": "slack.send_message",
      "params": {
        "body": {
          "channel": "#general",
          "text": "Hello from automation!"
        }
      }
    }
  ]
}
```

---

## 获取帮助

- 📖 详细指南：[MCP_CONFIGURATION_GUIDE.md](./MCP_CONFIGURATION_GUIDE.md)
- 🏗️ 架构文档：[docs/mcp/architecture.md](./mcp/architecture.md)
- 📝 开发指南：[docs/mcp/development-guide.md](./mcp/development-guide.md)
- 🔍 API参考：[docs/mcp/api-reference.md](./mcp/api-reference.md)
