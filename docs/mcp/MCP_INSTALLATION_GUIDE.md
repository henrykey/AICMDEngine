# MCP服务器安装和注册指南

**版本**: 1.0
**最后更新**: 2026-02-08

---

## 目录

1. [概述](#概述)
2. [方式1：内嵌式MCP服务器](#方式1内嵌式mcp服务器)
3. [方式2：外部MCP服务器](#方式2外部mcp服务器)
4. [配置示例](#配置示例)
5. [验证和测试](#验证和测试)

---

## 概述

AICMDEngine支持两种MCP服务器集成方式：

### 对比表

| 特性 | 内嵌式MCP | 外部MCP |
|------|----------|---------|
| **实现方式** | 继承BaseMCPServer类 | 通过stdio/WebSocket连接 |
| **部署位置** | 在AICMDEngine进程中运行 | 独立进程运行 |
| **通信方式** | 直接函数调用 | JSON-RPC 2.0协议 |
| **适用场景** | 集成内部API服务 | 使用社区/第三方MCP |
| **性能** | 高（无网络开销） | 中（有进程间通信开销） |
| **复杂度** | 需要编写代码 | 只需配置即可 |
| **隔离性** | 低（共享进程） | 高（独立进程） |

### 选择建议

✅ **使用内嵌式MCP**，如果：
- 需要集成内部REST API服务
- 需要高性能和低延迟
- 需要完全控制MCP实现
- API调用需要共享AICMDEngine的认证/租户上下文

✅ **使用外部MCP**，如果：
- 使用现成的社区MCP服务器
- 需要进程隔离和稳定性
- MCP由不同语言编写（如Node.js、Go）
- 希望通过配置快速添加

---

## 方式1：内嵌式MCP服务器

### 步骤1：创建MCP服务器类

在 `src/mcp_servers/` 目录下创建新文件：

```python
# src/mcp_servers/github_mcp.py

from typing import Optional, Dict, Any
from ..mcp import BaseMCPServer, Tool, ToolResult
from ..services.http_client import HTTPClient
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)

class GitHubMCPServer(BaseMCPServer):
    """
    GitHub API MCP服务器
    """

    def __init__(self, github_token: Optional[str] = None):
        """
        初始化GitHub MCP服务器

        Args:
            github_token: GitHub个人访问令牌
        """
        super().__init__("github", "1.0")
        self.github_token = github_token or settings.github_token
        self.base_url = "https://api.github.com"
        self.http_client = HTTPClient(base_url=self.base_url)
        self._register_tools()

    def _register_tools(self) -> None:
        """注册所有GitHub API工具"""

        # 工具1：获取仓库信息
        self.register_tool(Tool(
            name="get_repo",
            description="获取GitHub仓库信息",
            input_schema={
                "type": "object",
                "properties": {
                    "owner": {
                        "type": "string",
                        "description": "仓库所有者"
                    },
                    "repo": {
                        "type": "string",
                        "description": "仓库名称"
                    }
                },
                "required": ["owner", "repo"]
            },
            handler=self.get_repo
        ))

        # 工具2：列出仓库Issues
        self.register_tool(Tool(
            name="list_issues",
            description="列出仓库的Issues",
            input_schema={
                "type": "object",
                "properties": {
                    "owner": {
                        "type": "string",
                        "description": "仓库所有者"
                    },
                    "repo": {
                        "type": "string",
                        "description": "仓库名称"
                    },
                    "state": {
                        "type": "string",
                        "description": "Issue状态",
                        "enum": ["open", "closed", "all"],
                        "default": "open"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量",
                        "default": 10
                    }
                },
                "required": ["owner", "repo"]
            },
            handler=self.list_issues
        ))

        # 工具3：创建Issue
        self.register_tool(Tool(
            name="create_issue",
            description="创建新的Issue",
            input_schema={
                "type": "object",
                "properties": {
                    "owner": {
                        "type": "string",
                        "description": "仓库所有者"
                    },
                    "repo": {
                        "type": "string",
                        "description": "仓库名称"
                    },
                    "title": {
                        "type": "string",
                        "description": "Issue标题"
                    },
                    "body": {
                        "type": "string",
                        "description": "Issue内容"
                    }
                },
                "required": ["owner", "repo", "title"]
            },
            handler=self.create_issue
        ))

    async def get_repo(self, owner: str, repo: str, **kwargs) -> ToolResult:
        """获取仓库信息处理器"""
        try:
            response = await self.http_client.execute(
                command="GET /repos/{owner}/{repo}",
                params={
                    "path": {"owner": owner, "repo": repo}
                },
                auth_token=self.github_token,
                tenant_id=1  # GitHub不需要tenant_id
            )
            return ToolResult.success(str(response))
        except Exception as e:
            logger.error(f"Error getting repo: {e}")
            return ToolResult.error(str(e), error_code="GET_REPO_ERROR")

    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        limit: int = 10,
        **kwargs
    ) -> ToolResult:
        """列出Issues处理器"""
        try:
            response = await self.http_client.execute(
                command="GET /repos/{owner}/{repo}/issues",
                params={
                    "path": {"owner": owner, "repo": repo},
                    "query": {"state": state, "per_page": limit}
                },
                auth_token=self.github_token,
                tenant_id=1
            )
            return ToolResult.success(str(response))
        except Exception as e:
            logger.error(f"Error listing issues: {e}")
            return ToolResult.error(str(e), error_code="LIST_ISSUES_ERROR")

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        **kwargs
    ) -> ToolResult:
        """创建Issue处理器"""
        try:
            response = await self.http_client.execute(
                command="POST /repos/{owner}/{repo}/issues",
                params={
                    "path": {"owner": owner, "repo": repo},
                    "body": {"title": title, "body": body}
                },
                auth_token=self.github_token,
                tenant_id=1
            )
            return ToolResult.success(str(response))
        except Exception as e:
            logger.error(f"Error creating issue: {e}")
            return ToolResult.error(str(e), error_code="CREATE_ISSUE_ERROR")
```

### 步骤2：添加配置

在 `src/core/config.py` 中添加配置：

```python
from pydantic import Field

class Settings(BaseSettings):
    # ... 现有配置 ...

    # GitHub MCP配置
    github_token: str = Field(default="", env="GITHUB_TOKEN")
```

在 `.env` 文件中设置：

```bash
GITHUB_TOKEN=ghp_your_token_here
```

### 步骤3：注册MCP

在 `src/main.py` 中注册：

```python
from src.mcp_servers.github_mcp import GitHubMCPServer

@app.on_event("startup")
async def startup_db_client():
    # ... 现有代码 ...

    # 初始化MCP Registry
    mcp_registry = MCPRegistry()

    # 注册MCP服务器
    membership_mcp = MembershipMCPServer()
    test_mcp = TestMCPServer()
    github_mcp = GitHubMCPServer()  # 添加GitHub MCP

    mcp_registry.register_mcp(membership_mcp)
    mcp_registry.register_mcp(test_mcp)
    mcp_registry.register_mcp(github_mcp)  # 注册GitHub MCP

    # 设置全局MCP registry
    app.mcp_registry = mcp_registry
```

### 步骤4：验证

启动服务后检查日志：

```
INFO: Initialized MCP 'github' (version 1.0)
INFO: Registered MCP 'github'
INFO: Initialized MCP Registry with 3 servers:
INFO:   - membership (v2.0): 8 tools
INFO:   - test (v1.0): 2 tools
INFO:   - github (v1.0): 3 tools
```

---

## 方式2：外部MCP服务器

外部MCP服务器通过stdio或WebSocket与AICMDEngine通信。

### 架构

```
┌─────────────────────────────────────────┐
│         AICMDEngine                      │
│                                          │
│  ┌────────────────────────────────┐    │
│  │      MCPRegistry               │    │
│  │                                 │    │
│  │  ┌──────────────────────────┐ │    │
│  │  │ ExternalMCPServer         │ │    │
│  │  │ (Proxy Adapter)           │ │    │
│  │  └──────┬────────────────────┘ │    │
│  └─────────┼───────────────────────┘    │
└────────────┼────────────────────────────┘
             │ JSON-RPC 2.0
             │ (stdio or WebSocket)
     ┌───────▼────────────┐
     │ External MCP       │
     │ (Node.js/Go/Rust)  │
     └────────────────────┘
```

### 步骤1：创建外部MCP适配器

创建 `src/mcp/external_mcp.py`:

```python
"""
External MCP Server Adapter
支持通过stdio或WebSocket连接外部MCP服务器
"""

import asyncio
import json
from typing import Dict, Any, Optional
import logging
from .base_server import BaseMCPServer, Tool, ToolResult

logger = logging.getLogger(__name__)


class ExternalMCPServer(BaseMCPServer):
    """
    外部MCP服务器适配器

    通过stdio或WebSocket连接到外部MCP服务器，
    并将其工具暴露给MCPRegistry
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: list = None,
        transport: str = "stdio"
    ):
        """
        初始化外部MCP服务器适配器

        Args:
            name: MCP服务器名称
            command: 启动MCP服务器的命令
            args: 命令参数
            transport: 传输方式 (stdio 或 websocket)
        """
        super().__init__(name, "1.0")
        self.command = command
        self.args = args or []
        self.transport = transport
        self.process = None
        self.tools_cache = {}
        self._initialize_connection()

    def _initialize_connection(self):
        """初始化与外部MCP的连接"""
        if self.transport == "stdio":
            self._connect_stdio()
        elif self.transport == "websocket":
            self._connect_websocket()

    def _connect_stdio(self):
        """通过stdio连接外部MCP"""
        import subprocess

        try:
            # 启动外部MCP进程
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 发送initialize请求
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "AICMDEngine",
                        "version": "1.0.0"
                    }
                }
            }

            self._send_message(init_request)
            response = self._read_message()

            if response and "result" in response:
                logger.info(f"Connected to external MCP '{self.name}'")

                # 请求工具列表
                self._discover_tools()

        except Exception as e:
            logger.error(f"Failed to connect to external MCP '{self.name}': {e}")

    def _connect_websocket(self):
        """通过WebSocket连接外部MCP"""
        # TODO: 实现WebSocket连接
        logger.warning("WebSocket transport not yet implemented")

    def _send_message(self, message: dict):
        """发送消息到外部MCP"""
        if self.process and self.process.stdin:
            json_str = json.dumps(message)
            self.process.stdin.write(json_str + "\n")
            self.process.stdin.flush()

    def _read_message(self) -> Optional[dict]:
        """从外部MCP读取消息"""
        if self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if line:
                    return json.loads(line.strip())
            except Exception as e:
                logger.error(f"Error reading message: {e}")
        return None

    def _discover_tools(self):
        """发现外部MCP提供的工具"""
        try:
            # 请求工具列表
            list_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list"
            }

            self._send_message(list_request)
            response = self._read_message()

            if response and "result" in response:
                tools = response["result"].get("tools", [])

                # 注册所有发现的工具
                for tool_def in tools:
                    self._register_external_tool(tool_def)

                logger.info(f"Discovered {len(tools)} tools from external MCP '{self.name}'")

        except Exception as e:
            logger.error(f"Failed to discover tools: {e}")

    def _register_external_tool(self, tool_def: dict):
        """注册外部工具到本地MCP"""
        tool_name = tool_def["name"]
        self.tools_cache[tool_name] = tool_def

        # 创建本地工具包装器
        async def external_tool_wrapper(**kwargs):
            return await self._execute_external_tool(tool_name, kwargs)

        # 注册到MCP
        self.register_tool(Tool(
            name=tool_name,
            description=tool_def.get("description", ""),
            input_schema=tool_def.get("inputSchema", {}),
            handler=external_tool_wrapper
        ))

    async def _execute_external_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """执行外部工具"""
        try:
            request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            self._send_message(request)
            response = self._read_message()

            if response:
                if "error" in response:
                    error = response["error"]
                    return ToolResult.error(
                        error.get("message", "Unknown error"),
                        error_code=str(error.get("code", "UNKNOWN"))
                    )

                if "result" in response:
                    result = response["result"]
                    content = result.get("content", [])
                    if content and len(content) > 0:
                        text = content[0].get("text", "")
                        return ToolResult.success(text)

            return ToolResult.error("No response from external MCP")

        except Exception as e:
            logger.error(f"Error executing external tool '{tool_name}': {e}")
            return ToolResult.error(str(e))

    async def close(self):
        """关闭连接"""
        if self.process:
            self.process.terminate()
            self.process.wait()
```

### 步骤2：配置外部MCP

在 `src/core/config.py` 中添加配置：

```python
class Settings(BaseSettings):
    # ... 现有配置 ...

    # 外部MCP配置
    external_mcps: dict = Field(
        default={
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
                "transport": "stdio"
            },
            "git": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-git"],
                "transport": "stdio"
            }
        },
        env="EXTERNAL_MCPS"
    )
```

### 步骤3：注册外部MCP

在 `src/main.py` 中注册：

```python
from src.mcp.external_mcp import ExternalMCPServer

@app.on_event("startup")
async def startup_db_client():
    # ... 现有代码 ...

    mcp_registry = MCPRegistry()

    # 注册内嵌MCP
    membership_mcp = MembershipMCPServer()
    mcp_registry.register_mcp(membership_mcp)

    # 注册外部MCP
    for mcp_name, mcp_config in settings.external_mcps.items():
        try:
            external_mcp = ExternalMCPServer(
                name=mcp_name,
                command=mcp_config["command"],
                args=mcp_config.get("args", []),
                transport=mcp_config.get("transport", "stdio")
            )
            mcp_registry.register_mcp(external_mcp)
        except Exception as e:
            logger.error(f"Failed to register external MCP '{mcp_name}': {e}")

    app.mcp_registry = mcp_registry
```

### 步骤4：环境变量配置

在 `.env` 文件中配置：

```bash
# JSON格式配置外部MCP
EXTERNAL_MCPS='{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/username/projects"],
    "transport": "stdio"
  },
  "git": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-git", "/Users/username/projects"],
    "transport": "stdio"
  }
}'
```

---

## 配置示例

### 示例1：社区MCP服务器

常用社区MCP服务器：

```python
# 在config.py中配置
external_mcps = {
    # 文件系统访问
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
        "transport": "stdio"
    },

    # Git操作
    "git": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-git", "/path/to/repo"],
        "transport": "stdio"
    },

    # 数据库查询
    "sqlite": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "./mydb.sqlite"],
        "transport": "stdio"
    },

    # GitHub集成
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "transport": "stdio"
    },

    # Postgres数据库
    "postgres": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://..."],
        "transport": "stdio"
    }
}
```

### 示例2：自定义外部MCP

如果您自己开发了一个Node.js MCP服务器：

**MCP服务器代码** (`my-mcp-server.js`):

```javascript
#!/usr/bin/env node

const { Server } = require('@modelcontextprotocol/sdk/server/index.js');
const { StdioServerTransport } = require('@modelcontextprotocol/sdk/server/stdio.js');
const {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} = require('@modelcontextprotocol/sdk/types.js');

const server = new Server(
  {
    name: 'my-custom-mcp',
    version: '1.0.0',
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// 注册工具
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: 'my_tool',
        description: 'My custom tool',
        inputSchema: {
          type: 'object',
          properties: {
            param1: {
              type: 'string',
              description: 'First parameter'
            }
          },
          required: ['param1']
        }
      }
    ]
  };
});

// 处理工具调用
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === 'my_tool') {
    return {
      content: [{
        type: 'text',
        text: `Result: ${args.param1}`
      }]
    };
  }

  throw new Error(`Unknown tool: ${name}`);
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
```

**配置**:

```python
# 在config.py中
external_mcps = {
    "my_custom": {
        "command": "node",
        "args": ["/path/to/my-mcp-server.js"],
        "transport": "stdio"
    }
}
```

---

## 验证和测试

### 1. 检查MCP注册

```bash
curl http://localhost:8000/v1/mcp/servers
```

预期响应：

```json
{
  "servers": [
    {
      "name": "membership",
      "version": "2.0",
      "tools_count": 8,
      "tools": [...]
    },
    {
      "name": "filesystem",
      "version": "1.0",
      "tools_count": 5,
      "tools": [...]
    }
  ]
}
```

### 2. 测试工具调用

```bash
# 调用文件系统MCP的工具
curl -X POST http://localhost:8000/v1/mcp/execute \
  -H "Content-Type: application/json" \
  -d '{
    "mcp_name": "filesystem",
    "tool_name": "read_file",
    "arguments": {
      "path": "/allowed/path/file.txt"
    }
  }'
```

### 3. 查看日志

```bash
# 启动时查看MCP注册日志
python -m src.main

# 应该看到类似输出:
INFO: Registered MCP 'membership'
INFO: Registered MCP 'filesystem'
INFO: Discovered 5 tools from external MCP 'filesystem'
INFO: Initialized MCP Registry with 2 servers
```

### 4. 前端使用

在计划执行中使用：

```typescript
const plan = [
  {
    step: 1,
    command: "filesystem.read_file",
    description: "读取文件内容",
    params: {
      path: "/allowed/path/config.json"
    }
  },
  {
    step: 2,
    command: "git.clone",
    description: "克隆Git仓库",
    params: {
      url: "https://github.com/user/repo.git"
    }
  }
];
```

---

## 故障排除

### 问题1：外部MCP无法启动

**症状**: 日志显示"Failed to connect to external MCP"

**解决**:
1. 检查命令是否正确: `which npx` 或 `which node`
2. 手动测试外部MCP: `npx @modelcontextprotocol/server-filesystem /path`
3. 查看stderr输出获取详细错误信息

### 问题2：工具未发现

**症状**: MCP注册成功但tools_count为0

**解决**:
1. 检查外部MCP是否实现了`tools/list`方法
2. 确认protocolVersion为"2024-11-05"
3. 查看AICMDEngine日志中的JSON-RPC通信

### 问题3：工具调用失败

**症状**: 调用工具时返回错误

**解决**:
1. 检查参数格式是否与input_schema一致
2. 确认外部MCP进程仍在运行
3. 查看外部MCP的stderr日志

### 问题4：权限问题

**症状**: 文件系统MCP拒绝访问

**解决**:
1. 确认args中指定的路径有访问权限
2. 检查路径是否在allowed列表中
3. 验证文件/目录的Unix权限

---

## 最佳实践

### 1. 安全性

- ⚠️ **限制文件系统访问**: 只允许必要的目录
- ⚠️ **使用只读工具**: 优先使用read_*而非write_*
- ⚠️ **验证参数**: 在内嵌MCP中验证所有输入
- ⚠️ **隔离进程**: 外部MCP应运行在受限环境中

### 2. 性能

- ✅ **缓存工具列表**: 避免频繁请求tools/list
- ✅ **重用连接**: 保持外部MCP进程运行
- ✅ **异步执行**: 使用asyncio并发执行多个工具
- ✅ **超时控制**: 为每个工具调用设置超时

### 3. 可维护性

- ✅ **版本管理**: 在配置中记录MCP版本
- ✅ **健康检查**: 定期ping外部MCP确保可用
- ✅ **错误处理**: 捕获并记录所有异常
- ✅ **文档维护**: 记录每个MCP的用途和配置

---

## 参考资源

- [MCP官方规范](https://modelcontextprotocol.io/)
- [社区MCP服务器列表](https://github.com/modelcontextprotocol/servers)
- [MCP SDK文档](https://github.com/modelcontextprotocol/typescript-sdk)
- [AICMDEngine MCP架构](./architecture.md)
- [MCP配置指南](./MCP_CONFIGURATION_GUIDE.md)

---

**文档维护**: 随MCP框架更新同步更新
**问题反馈**: 请在项目issue中提出
