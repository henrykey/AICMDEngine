# AICMDEngine MCP Framework Documentation

**Model Context Protocol (MCP) Framework for AICMDEngine**

## 📖 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Creating MCP Servers](#creating-mcp-servers)
- [API Reference](#api-reference)
- [Management Interface](#management-interface)
- [Best Practices](#best-practices)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## 🎯 Overview

The AICMDEngine MCP Framework provides a robust implementation of the Model Context Protocol (MCP) for managing modular AI command execution. This framework allows you to:

- **Decommon monolithic systems**: Break down large AI systems into manageable MCP servers
- **Modular API integration**: Each MCP server handles specific APIs and domains
- **Real-time communication**: Dynamic tool discovery and execution
- **Scalable architecture**: Easy to add new MCP servers without affecting existing ones
- **Management interface**: Complete UI for monitoring and managing MCP servers

### Key Benefits

✅ **Modularity**: Each API command set is managed by a dedicated MCP server
✅ **Scalability**: Add new MCP servers without modifying core logic
✅ **Real-time**: Dynamic command discovery and execution
✅ **Monitoring**: Built-in health checks and performance tracking
✅ **Management**: Complete UI for server administration

## 🏗️ Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AICMDEngine Core                         │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ Planning     │  │ LLM         │  │ Command     │       │
│  │ Engine      │◄─┤ Management │◄─│ Sets        │       │
│  └─────────────┘  └─────────────┘  └─────────────┘       │
│           │             │              │                    │
│           ▼             ▼              ▼                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                  MCP Registry                           │ │
│  │                                                         │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │ │
│  │  │ Membership  │  │     MCP     │  │    Test      │    │ │
│  │  │   MCP       │  │   Server    │  │     MCP      │    │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                              │                                │
│                              ▼                                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │               External APIs                             │ │
│  │                                                         │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │ │
│  │  │ Membership │  │   Payments  │  │   Analytics │    │ │
│  │  │     API     │  │     API     │  │     API     │    │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘    │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. **MCPRegistry**
Central registry for managing all MCP servers. Handles:
- Server registration and discovery
- Tool execution routing
- Health monitoring
- Server lifecycle management

#### 2. **BaseMCPServer**
Abstract base class for all MCP servers. Provides:
- Tool registration system
- Standardized interface for tool execution
- Metadata management
- Status tracking

#### 3. **Tool System**
Individual tools that correspond to API operations:
- Schema validation
- Parameter handling
- Result formatting
- Error management

#### 4. **Management Interface**
React-based UI for:
- Server monitoring
- Tool discovery
- Performance tracking
- Server management

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- FastAPI
- React/TypeScript for frontend
- MongoDB for persistence

### 1. Create Your First MCP Server

```python
from src.mcp.base_server import BaseMCPServer
from src.mcp.tool import Tool

class MyAPIMCP(BaseMCPServer):
    def __init__(self):
        super().__init__("my-api", "1.0.0")
        self.description = "MCP server for My API"
        self.author = "Your Name"

        # Register tools
        self.register_tool(Tool(
            name="create_user",
            description="Create a new user",
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"}
                },
                "required": ["name", "email"]
            },
            handler=self.create_user_handler
        ))

    async def create_user_handler(self, name: str, email: str):
        # Implement your API logic here
        return {"success": True, "user_id": "123"}
```

### 2. Register the MCP Server

```python
from src.mcp.registry import MCPRegistry
from src.main import app

# Create and register MCP server
registry = MCPRegistry()
mcp_server = MyAPIMCP()
registry.register_mcp(mcp_server)

# Attach to FastAPI app
app.mcp_registry = registry
```

### 3. Access the Management Interface

Visit the Settings page in your AICMDEngine UI and navigate to the "MCP Management" tab to view and manage your new MCP server.

## 🔧 Creating MCP Servers

### Step-by-Step Guide

#### 1. Inherit from BaseMCPServer

```python
from src.mcp.base_server import BaseMCPServer

class MyMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__("my-service", "1.0.0")
        self.description = "MCP server for My Service"
        self.author = "Your Team"

        # Initialize tools
        self.initialize_tools()

    def initialize_tools(self):
        """Register all tools for this MCP server"""
        pass
```

#### 2. Create Tools

```python
from src.mcp.tool import Tool

# Create a simple tool
create_user_tool = Tool(
    name="create_user",
    description="Create a new user account",
    schema={
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "Username"},
            "email": {"type": "string", "format": "email"},
            "role": {"type": "string", "enum": ["admin", "user", "guest"]}
        },
        "required": ["username", "email"]
    },
    handler=self.create_user_handler
)

self.register_tool(create_user_tool)
```

#### 3. Implement Tool Handlers

```python
async def create_user_handler(self, username: str, email: str, role: str = "user"):
    """
    Handle the create_user tool execution

    Args:
        username: User username
        email: User email address
        role: User role (admin, user, guest)

    Returns:
        ToolResult with success/failure status
    """
    try:
        # Call your API
        response = requests.post(
            "https://api.example.com/users",
            json={"username": username, "email": error},
            headers={"Authorization": f"Bearer {self.api_key}"}
        )

        if response.status_code == 201:
            return {
                "success": True,
                "data": response.json(),
                "message": "User created successfully"
            }
        else:
            return {
                "success": False,
                "error": f"API error: {response.status_code}",
                "details": response.text
            }

    except Exception as e:
        return {
            "success": False,
            "error": "Execution error",
            "details": str(e)
        }
```

#### 4. Add Error Handling

```python
async def risky_handler(self, param1: str, param2: int):
    try:
        # Business logic
        result = await self.some_operation(param1, param2)
        return ToolResult.success(result)

    except requests.exceptions.ConnectionError:
        return ToolResult.error("Connection failed to external API")
    except ValueError as e:
        return ToolResult.error(f"Invalid parameters: {str(e)}", "INVALID_PARAMS")
    except Exception as e:
        logger.error(f"Unexpected error in risky_handler: {e}")
        return ToolResult.error("Internal server error", "INTERNAL_ERROR")
```

#### 5. Add Metadata

```python
def __init__(self):
    super().__init__("payment-service", "2.1.0")
    self.description = "Payment processing MCP server"
    self.author = "Payment Team"
    self.dependencies = ["database", "redis", "logging"]

    # Add custom metadata
    self.metadata = {
        "api_version": "v2",
        "rate_limit": "1000/hour",
        "supported_currencies": ["USD", "EUR", "CNY"]
    }
```

## 📋 API Reference

### MCP Registry API

#### List All Servers
```http
GET /v1/mcp/servers
```

Response:
```json
{
  "servers": [
    {
      "name": "membership",
      "type": "custom",
      "endpoint": "mcp://membership",
      "status": "running",
      "health_score": 85,
      "tools_count": 7,
      "commands_count": 7,
      "metadata": {
        "description": "Membership API MCP Server",
        "version": "2.0",
        "author": "Unknown",
        "dependencies": []
      }
    }
  ]
}
```

#### Server Management
```http
POST /v1/mcp/servers/{name}/refresh    # Refresh server status
POST /v1/mcp/servers/{name}/start      # Start server
POST /v1/mcp/servers/{name}/stop       # Stop server
DELETE /v1/mcp/servers/{name}          # Delete server
```

### Tool Execution API

#### Execute Tool
```http
POST /v1/mcp/servers/{server_name}/tools/{tool_name}
Content-Type: application/json

{
  "param1": "value1",
  "param2": 42
}
```

#### List Tools
```http
GET /v1/mcp/servers/{server_name}/tools
```

## 🖥️ Management Interface

### Access the UI

1. Navigate to Settings in the AICMDEngine UI
2. Click on "MCP Management" tab
3. View all registered MCP servers

### Features

#### Server List
- **Status Indicators**: Visual badges for server status
- **Health Scores**: 0-100% health monitoring
- **Tool Count**: Number of available tools
- **Quick Actions**: Start, stop, refresh, delete buttons

#### Server Details
- **Configuration**: Server metadata and settings
- **Tools**: Complete tool inventory and schemas
- **Monitoring**: Performance metrics and logs
- **Commands**: Command execution history

### Management Actions

```python
# Programmatically manage servers
registry = app.mcp_registry

# Start a server
await registry.initialize_mcp("membership")

# Stop a server (remove from registry)
registry.remove_mcp("membership")

# Refresh server status
mcp = registry.get_mcp("membership")
mcp.last_heartbeat = datetime.now()
```

## 💡 Best Practices

### 1. Tool Design

#### Good Tool Schema
```python
Tool(
    name="create_user",
    description="Create a new user account",
    schema={
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "Unique username for the user",
                "minLength": 3,
                "maxLength": 50
            },
            "email": {
                "type": "string",
                "format": "email",
                "description": "Valid email address"
            },
            "is_active": {
                "type": "boolean",
                "default": True,
                "description": "Whether the user account is active"
            }
        },
        "required": ["username", "email"],
        "additionalProperties": False
    },
    handler=self.create_user_handler
)
```

### 2. Error Handling

#### Handle Different Error Types
```python
async def api_call_handler(self, endpoint: str, params: dict):
    try:
        response = await self.call_external_api(endpoint, params)
        return ToolResult.success(response.json())

    except requests.exceptions.Timeout:
        return ToolResult.error("Request timed out", "TIMEOUT")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return ToolResult.error("Authentication failed", "AUTH_ERROR")
        elif e.response.status_code == 404:
            return ToolResult.error("Resource not found", "NOT_FOUND")
        else:
            return ToolResult.error(f"API error: {e.response.status_code}", "API_ERROR")
    except Exception as e:
        logger.error(f"Unexpected error in api_call_handler: {e}")
        return ToolResult.error("Internal server error", "INTERNAL_ERROR")
```

### 3. Performance Optimization

#### Cache Results
```python
import asyncio
from functools import lru_cache

class MyMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__("my-service", "1.0.0")
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes

    @lru_cache(maxsize=128)
    def _get_cached_data(self, cache_key: str):
        """Get data from cache with LRU eviction"""
        return self._cache.get(cache_key)

    async def data_handler(self, query: str):
        # Check cache first
        cache_key = f"data:{hash(query)}"
        cached_result = self._get_cached_data(cache_key)

        if cached_result and (datetime.now() - cached_result['timestamp']).seconds < self._cache_ttl:
            return ToolResult.success(cached_result['data'])

        # Call API and cache result
        result = await self.call_expensive_api(query)
        self._cache[cache_key] = {
            'data': result,
            'timestamp': datetime.now()
        }

        return ToolResult.success(result)
```

### 4. Security

#### Validate Input
```python
async def sensitive_handler(self, user_id: str, action: str):
    # Validate input
    if not re.match(r'^[a-f0-9]{24}$', user_id):
        return ToolResult.error("Invalid user ID format", "INVALID_INPUT")

    if action not in ["read", "write", "delete"]:
        return ToolResult.error("Invalid action", "INVALID_INPUT")

    # Check permissions
    if not await self.check_permission(user_id, action):
        return ToolResult.error("Permission denied", "PERMISSION_DENIED")

    # Execute action
    result = await self.perform_action(user_id, action)
    return ToolResult.success(result)
```

## 📚 Examples

### Example 1: Simple API MCP Server

```python
from src.mcp.base_server import BaseMCPServer
from src.mcp.tool import Tool
import requests

class WeatherMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__("weather-api", "1.0.0")
        self.description = "Weather information API server"
        self.api_key = "your-api-key-here"

        # Register tools
        self.register_tool(Tool(
            name="get_current_weather",
            description="Get current weather for a city",
            schema={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "units": {"type": "string", "enum": ["metric", "imperial"], "default": "metric"}
                },
                "required": ["city"]
            },
            handler=self.get_current_weather
        ))

    async def get_current_weather(self, city: str, units: str = "metric"):
        """Get current weather from OpenWeatherMap API"""
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather"
            params = {
                "q": city,
                "appid": self.api_key,
                "units": units
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            return {
                "success": True,
                "data": {
                    "city": data["name"],
                    "temperature": data["main"]["temp"],
                    "description": data["weather"][0]["description"],
                    "humidity": data["main"]["humidity"],
                    "wind_speed": data["wind"]["speed"]
                }
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"Weather API error: {str(e)}",
                "details": "Failed to fetch weather data"
            }
```

### Example 2: Database MCP Server

```python
from src.mcp.base_server import BaseMCPServer
from src.mcp.tool import Tool
import motor.motor_asyncio as motor

class DatabaseMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__("database", "1.0.0")
        self.description = "Database operations MCP server"
        self.author = "Database Team"

        # Initialize MongoDB connection
        self.client = motor.AsyncIOMotorClient("mongodb://localhost:27017")
        self.db = self.client["aicmde"]

        # Register tools
        self.register_tool(Tool(
            name="find_documents",
            description="Find documents in a collection",
            schema={
                "type": "object",
                "properties": {
                    "collection": {"type": "string", "description": "Collection name"},
                    "query": {"type": "object", "description": "Query filter"},
                    "limit": {"type": "integer", "default": 10, "description": "Maximum results"}
                },
                "required": ["collection"]
            },
            handler=self.find_documents
        ))

    async def find_documents(self, collection: str, query: dict = None, limit: int = 10):
        """Find documents in MongoDB collection"""
        try:
            if query is None:
                query = {}

            coll = self.db[collection]
            cursor = coll.find(query).limit(limit)
            documents = await cursor.to_list(length=limit)

            return {
                "success": True,
                "data": {
                    "count": len(documents),
                    "documents": documents
                }
            }

        except Exception as e:
            logger.error(f"Database error in find_documents: {e}")
            return {
                "success": False,
                "error": "Database operation failed",
                "details": str(e)
            }

    async def initialize(self):
        """Initialize the database server"""
        try:
            # Test connection
            await self.db.command('ping')
            self.is_initialized = True
            logger.info("Database MCP server initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database MCP server: {e}")
            self.is_initialized = False
```

## 🔍 Troubleshooting

### Common Issues

#### 1. MCP Server Not Showing in UI

**Problem**: Your MCP server doesn't appear in the management interface.

**Solution**:
```python
# Check if server is properly registered
registry = app.mcp_registry
servers = registry.get_all_mcps()
print(f"Registered servers: {[mcp.name for mcp in servers]}")

# Check if server has tools
if len(mcp.get_tools()) == 0:
    print("Server has no tools - register tools in __init__")
```

#### 2. Tool Execution Fails

**Problem**: Tools return execution errors.

**Debug Steps**:
```python
# Check tool handler
tool = mcp.get_tool("your_tool_name")
if not tool:
    print("Tool not found - check registration")

# Test handler directly
try:
    result = await tool.handler(**test_params)
    print(f"Handler result: {result}")
except Exception as e:
    print(f"Handler error: {e}")
```

#### 3. Server Initialization Issues

**Problem**: MCP server shows as "stopped" status.

**Solution**:
```python
# Check if server has initialize method
mcp = registry.get_mcp("your_server")
if hasattr(mcp, 'initialize'):
    await registry.initialize_mcp("your_server")
else:
    print("Server doesn't have initialize method")
```

#### 4. API Connection Errors

**Problem**: MCP server can't connect to external APIs.

**Debugging Tips**:
```python
# Test API connection manually
import requests
try:
    response = requests.get("https://api.example.com/health", timeout=5)
    print(f"API status: {response.status_code}")
except requests.exceptions.RequestException as e:
    print(f"Connection error: {e}")

# Check network connectivity
# Add retries and timeout to your API calls
```

### Logging

Enable detailed logging for debugging:

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# In your MCP server
logger = logging.getLogger(__name__)

async def some_handler(self):
    logger.info("Starting some_handler")
    try:
        result = await self.some_operation()
        logger.info(f"Operation successful: {result}")
        return ToolResult.success(result)
    except Exception as e:
        logger.error(f"Operation failed: {e}", exc_info=True)
        return ToolResult.error(str(e))
```

## 📊 Performance Monitoring

### Monitor Server Performance

```python
import time
from contextlib import asynccontextmanager

class MonitoredMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__("monitored-service", "1.0.0")
        self.performance_metrics = {
            "total_calls": 0,
            "total_time": 0,
            "errors": 0
        }

    @asynccontextmanager
    async def monitor_performance(self, operation_name: str):
        start_time = time.time()
        try:
            yield
        except Exception:
            self.performance_metrics["errors"] += 1
            raise
        finally:
            duration = time.time() - start_time
            self.performance_metrics["total_calls"] += 1
            self.performance_metrics["total_time"] += duration

            # Log performance
            avg_time = self.performance_metrics["total_time"] / self.performance_metrics["total_calls"]
            logger.info(f"{operation_name} completed in {duration:.3f}s (avg: {avg_time:.3f}s)")

    async def monitored_handler(self, param1: str):
        async with self.monitor_performance("monitored_handler"):
            # Your business logic here
            result = await self.some_operation(param1)
            return ToolResult.success(result)
```

## 🤝 Contributing

To contribute to the MCP Framework:

1. Fork the repository
2. Create a feature branch for your MCP server
3. Follow the coding standards and patterns
4. Add tests for your tools
5. Update documentation
6. Submit a pull request

### Code Standards

- Use type hints for all function signatures
- Document all public methods
- Handle errors gracefully
- Follow the existing code style
- Include unit tests
- Update relevant documentation

---

**Last Updated**: 2026-01-09
**Version**: 1.0.0
**Maintainers**: AICMDEngine Team