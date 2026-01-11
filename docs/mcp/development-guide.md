# MCP Development Guide

This guide provides step-by-step instructions for developing MCP (Model Context Protocol) servers in the AICMDEngine framework.

## Table of Contents

1. [Development Setup](#development-setup)
2. [Creating Your First MCP Server](#creating-your-first-mcp-server)
3. [Tool Development Best Practices](#tool-development-best-practices)
4. [Testing Your MCP Server](#testing-your-mcp-server)
5. [Debugging Techniques](#debugging-techniques)
6. [Deployment Process](#deployment-process)
7. [Advanced Topics](#advanced-topics)

## Development Setup

### Prerequisites

Before developing MCP servers, ensure you have:

```bash
# Python 3.8+ with pip
python --version

# Install development dependencies
pip install -r requirements-dev.txt

# Install MCP SDK
pip install mcp
```

### Project Structure

```
src/
├── mcp/
│   ├── __init__.py
│   ├── base_server.py          # Base MCP Server class
│   ├── registry.py             # MCP Registry for server management
│   └── result.py               # ToolResult classes
└── mcp_servers/
    ├── __init__.py
    ├── membership/             # Example MCP server
    └── your_server/             # Your custom MCP server
```

### Creating a New MCP Server Directory

```bash
# Create MCP server directory
mkdir -p src/mcp_servers/your_server

# Create necessary files
touch src/mcp_servers/your_server/__init__.py
touch src/mcp_servers/your_server/server.py
touch src/mcp_servers/your_server/config.py
```

## Creating Your First MCP Server

### Step 1: Create the Server Class

Create `src/mcp_servers/your_server/server.py`:

```python
"""
Your custom MCP Server implementation.
"""

from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from src.mcp.base_server import BaseMCPServer
from src.mcp.result import ToolResult

logger = logging.getLogger(__name__)


class YourMCPServer(BaseMCPServer):
    """
    Example MCP Server demonstrating basic functionality.
    """

    def __init__(self):
        super().__init__(
            name="your-server",
            version="1.0.0",
            description="Your custom MCP server for AICMDEngine",
            author="Your Name",
            dependencies=[]
        )

        # Initialize your server-specific state here
        self.counter = 0
```

### Step 2: Define Tools

Add tool definitions to your server class:

```python
    def register_tools(self) -> None:
        """Register all available tools."""
        self.register_tool(
            name="greet",
            description="Generate a greeting message",
            schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name to greet",
                        "minLength": 1,
                        "maxLength": 100
                    },
                    "enthusiasm": {
                        "type": "integer",
                        "description": "Enthusiasm level (1-10)",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5
                    }
                },
                "required": ["name"]
            },
            handler=self.handle_greet
        )

        self.register_tool(
            name="get_status",
            description="Get current server status",
            schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=self.handle_get_status
        )
```

### Step 3: Implement Tool Handlers

Create async methods for each tool:

```python
    async def handle_greet(self, **kwargs) -> ToolResult:
        """
        Handle the greet tool.

        Args:
            name: Name to greet
            enthusiasm: Enthusiasm level (1-10)

        Returns:
            ToolResult with greeting message
        """
        try:
            name = kwargs.get("name")
            enthusiasm = kwargs.get("enthusiasm", 5)

            if not name:
                return ToolResult.error("Name parameter is required")

            # Generate greeting based on enthusiasm
            exclamation = "!" * enthusiasm
            message = f"Hello, {name}{exclamation}"

            # Update counter
            self.counter += 1

            logger.info(f"Generated greeting for {name} with enthusiasm {enthusiasm}")

            return ToolResult.success(
                content=message,
                metadata={
                    "greeting_count": self.counter,
                    "enthusiasm_level": enthusiasm
                }
            )

        except Exception as e:
            logger.error(f"Error in greet tool: {e}")
            return ToolResult.error(f"Failed to generate greeting: {str(e)}")

    async def handle_get_status(self, **kwargs) -> ToolResult:
        """
        Handle the get_status tool.

        Returns:
            ToolResult with server status information
        """
        try:
            status_info = {
                "server_name": self.name,
                "version": self.version,
                "uptime": datetime.now().isoformat(),
                "total_calls": self.counter,
                "is_initialized": self.is_initialized,
                "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None
            }

            return ToolResult.success(
                content="Server status retrieved successfully",
                metadata=status_info
            )

        except Exception as e:
            logger.error(f"Error in get_status tool: {e}")
            return ToolResult.error(f"Failed to get status: {str(e)}")
```

### Step 4: Register Your Server

Add your server to the application startup in `main.py`:

```python
from src.mcp_servers.membership.membership_server import MembershipMCPServer
from src.mcp_servers.your_server.server import YourMCPServer

# ... existing imports ...

app = FastAPI()

# Initialize MCP Registry
mcp_registry = MCPRegistry()

# Register MCP servers
mcp_registry.register_mcp(MembershipMCPServer())
mcp_registry.register_mcp(YourMCPServer())

# Attach registry to app
app.state.mcp_registry = mcp_registry

# Include routers
app.include_router(mcp_router, prefix="/v1/mcp")
```

### Step 5: Test Your Server

```bash
# Start the application
python main.py

# Test your server via API
curl -X GET "http://localhost:8000/v1/mcp/servers/your-server"
```

## Tool Development Best Practices

### 1. Schema Design

Always provide clear, comprehensive JSON schemas:

```python
# Good schema example
schema = {
    "type": "object",
    "properties": {
        "email": {
            "type": "string",
            "format": "email",  # Use format validation
            "description": "User email address"
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 10,
            "description": "Maximum number of results"
        }
    },
    "required": ["email"],
    "additionalProperties": False
}
```

### 2. Error Handling

Handle different error types appropriately:

```python
async def handle_tool(self, **kwargs) -> ToolResult:
    try:
        # Input validation
        if not kwargs.get("required_param"):
            return ToolResult.error(
                "Missing required parameter",
                error_code="MISSING_PARAMETER"
            )

        # External API calls
        try:
            result = await external_api_call(**kwargs)
        except TimeoutError:
            return ToolResult.error(
                "Request timeout",
                error_code="TIMEOUT_ERROR"
            )
        except HTTPError as e:
            if e.status_code == 401:
                return ToolResult.error(
                    "Authentication failed",
                    error_code="AUTH_ERROR"
                )
            elif e.status_code == 404:
                return ToolResult.error(
                    "Resource not found",
                    error_code="NOT_FOUND"
                )
            else:
                return ToolResult.error(
                    f"API error: {e.status_code}",
                    error_code="API_ERROR"
                )

        # Business logic
        if not result.get("success"):
            return ToolResult.error(
                "Business rule violation",
                error_code="BUSINESS_RULE_ERROR"
            )

        return ToolResult.success(
            content="Operation completed successfully",
            metadata=result
        )

    except Exception as e:
        logger.error(f"Unexpected error in tool: {e}")
        return ToolResult.error(
            f"Internal error: {str(e)}",
            error_code="INTERNAL_ERROR"
        )
```

### 3. Performance Optimization

Use caching for expensive operations:

```python
from functools import lru_cache
import asyncio

class OptimizedMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__()
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes

    @lru_cache(maxsize=128)
    def _expensive_computation(self, input_data: str) -> str:
        """Cached expensive computation."""
        # Your expensive logic here
        return result

    async def handle_cached_operation(self, **kwargs) -> ToolResult:
        """Handle operation with caching."""
        cache_key = kwargs.get("input_data")

        # Check cache
        if cache_key in self.cache:
            cached_result, timestamp = self.cache[cache_key]
            if datetime.now().timestamp() - timestamp < self.cache_ttl:
                return ToolResult.success(
                    content="Cached result",
                    metadata=cached_result
                )

        # Compute and cache
        result = self._expensive_computation(cache_key)
        self.cache[cache_key] = (result, datetime.now().timestamp())

        return ToolResult.success(content=result)
```

### 4. Logging

Implement comprehensive logging:

```python
import logging
from typing import Dict, Any

class LoggedMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__()
        # Configure logger for your server
        self.logger = logging.getLogger(f"mcp.{self.name}")
        self.logger.setLevel(logging.INFO)

        # Add console handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def handle_logged_operation(self, **kwargs) -> ToolResult:
        """Handle operation with comprehensive logging."""
        operation_id = f"{self.name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Log request
        self.logger.info(
            f"Starting operation {operation_id}",
            extra={
                "operation_id": operation_id,
                "input": kwargs,
                "tool": "logged_operation"
            }
        )

        start_time = datetime.now()

        try:
            # Execute operation
            result = await self._execute_operation(**kwargs)

            # Log success
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.info(
                f"Completed operation {operation_id} in {duration:.2f}s",
                extra={
                    "operation_id": operation_id,
                    "duration": duration,
                    "success": True
                }
            )

            return ToolResult.success(content=result)

        except Exception as e:
            # Log error
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.error(
                f"Failed operation {operation_id} after {duration:.2f}s: {e}",
                extra={
                    "operation_id": operation_id,
                    "duration": duration,
                    "error": str(e),
                    "success": False
                }
            )

            return ToolResult.error(str(e))
```

## Testing Your MCP Server

### Unit Testing

Create test file `tests/test_your_server.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from src.mcp_servers.your_server.server import YourMCPServer

class TestYourMCPServer:
    @pytest.fixture
    def server(self):
        return YourMCPServer()

    @pytest.mark.asyncio
    async def test_greet_success(self, server):
        """Test successful greeting."""
        result = await server.handle_greet(name="Test", enthusiasm=3)

        assert result.success is True
        assert "Hello, Test!!!" in result.content
        assert result.metadata["greeting_count"] == 1

    @pytest.mark.asyncio
    async def test_greet_missing_name(self, server):
        """Test greeting without name."""
        result = await server.handle_greet(enthusiasm=5)

        assert result.success is False
        assert "required" in result.content

    @pytest.mark.asyncio
    async def test_get_status(self, server):
        """Test status retrieval."""
        # Call greet first to increment counter
        await server.handle_greet(name="Test", enthusiasm=1)

        result = await server.handle_get_status()

        assert result.success is True
        assert "status retrieved successfully" in result.content
        assert "total_calls" in result.metadata
        assert result.metadata["total_calls"] == 1
```

### Integration Testing

Test your server with the registry:

```python
# tests/test_integration.py
import pytest
from src.mcp.registry import MCPRegistry
from src.mcp_servers.your_server.server import YourMCPServer

class TestMCPIntegration:
    @pytest.mark.asyncio
    async def test_server_registration(self):
        """Test server registration and execution."""
        registry = MCPRegistry()
        server = YourMCPServer()

        # Register server
        registry.register_mcp(server)

        # Test server retrieval
        retrieved_server = registry.get_mcp("your-server")
        assert retrieved_server is not None
        assert retrieved_server.name == "your-server"

        # Test tool execution
        result = await registry.execute_command(
            "your-server",
            "greet",
            name="Integration Test"
        )

        assert result.success is True
        assert "Hello, Integration Test" in result.content

    @pytest.mark.asyncio
    async def test_server_initialization(self):
        """Test server initialization."""
        registry = MCPRegistry()
        server = YourMCPServer()

        # Test initialization
        success = await registry.initialize_mcp("your-server")
        assert success is True
        assert server.is_initialized is True
```

### API Testing

Test your endpoints:

```bash
# Test server listing
curl -X GET "http://localhost:8000/v1/mcp/servers" | jq '.servers[] | select(.name == "your-server")'

# Test tool execution
curl -X POST "http://localhost:8000/v1/mcp/servers/your-server/tools/greet" \
  -H "Content-Type: application/json" \
  -d '{"name": "API Test", "enthusiasm": 5}'

# Test server status
curl -X GET "http://localhost:8000/v1/mcp/servers/your-server" | jq
```

## Debugging Techniques

### 1. Enable Debug Logging

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Or for specific module
logger = logging.getLogger("mcp.your-server")
logger.setLevel(logging.DEBUG)
```

### 2. Use Debug Middleware

Add debug middleware to `main.py`:

```python
@app.middleware("http")
async def debug_middleware(request: Request, call_next):
    start_time = datetime.now()

    # Log request
    logger.info(f"Incoming request: {request.method} {request.url}")

    try:
        response = await call_next(request)
        duration = (datetime.now() - start_time).total_seconds()

        # Log response
        logger.info(
            f"Response: {response.status_code} in {duration:.2f}s",
            extra={
                "method": request.method,
                "url": str(request.url),
                "status_code": response.status_code,
                "duration": duration
            }
        )

        return response

    except Exception as e:
        logger.error(f"Request failed: {e}")
        raise
```

### 3. Debug Tool Execution

Add debug logging to your tools:

```python
async def handle_debug_tool(self, **kwargs) -> ToolResult:
    """Debug tool for testing and diagnostics."""
    try:
        # Log all input parameters
        self.logger.debug(f"Tool input: {kwargs}")

        # Simulate some processing
        await asyncio.sleep(0.1)  # Simulate async work

        # Log output
        output = {
            "input_received": kwargs,
            "processing_time": "0.1s",
            "timestamp": datetime.now().isoformat()
        }

        self.logger.debug(f"Tool output: {output}")

        return ToolResult.success(
            content="Debug operation completed",
            metadata=output
        )

    except Exception as e:
        self.logger.error(f"Debug tool error: {e}", exc_info=True)
        return ToolResult.error(str(e))
```

### 4. Interactive Debugging

Use Python debugger in your tools:

```python
import pdb

async def handle_debug_with_pdb(self, **kwargs) -> ToolResult:
    """Tool with interactive debugging."""
    try:
        # Set breakpoint
        pdb.set_trace()

        # Your tool logic here
        result = f"Processed: {kwargs}"

        return ToolResult.success(content=result)

    except Exception as e:
        return ToolResult.error(str(e))
```

## Deployment Process

### 1. Prepare for Production

```python
# production_settings.py
import os
from typing import Dict, Any

class ProductionSettings:
    # Configuration for production MCP servers
    LOG_LEVEL = os.getenv("MCP_LOG_LEVEL", "INFO")
    CACHE_TTL = int(os.getenv("MCP_CACHE_TTL", "300"))
    MAX_RETRIES = int(os.getenv("MCP_MAX_RETRIES", "3"))
    TIMEOUT = int(os.getenv("MCP_TIMEOUT", "30"))
```

### 2. Create Docker Configuration

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY main.py .

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3. Environment Configuration

```bash
# .env
MCP_LOG_LEVEL=INFO
MCP_CACHE_TTL=300
MCP_MAX_RETRIES=3
MCP_TIMEOUT=30

# Database configuration
DATABASE_URL=mongodb://localhost:27017/aicmdengine

# External API keys
EXTERNAL_API_KEY=your-api-key-here
```

### 4. Deployment Script

```bash
#!/bin/bash
# deploy.sh

echo "Building and deploying MCP server..."

# Build Docker image
docker build -t aicmdengine-mcp .

# Run container
docker run -d \
  --name mcp-server \
  -p 8000:8000 \
  --env-file .env \
  aicmdengine-mcp

echo "Deployment complete!"
```

### 5. Health Check

```python
async def handle_health_check(self, **kwargs) -> ToolResult:
    """Health check for monitoring systems."""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "uptime": (datetime.now() - self.start_time).total_seconds() if hasattr(self, 'start_time') else 0,
            "version": self.version,
            "tools_count": len(self.tools),
            "is_initialized": self.is_initialized
        }

        return ToolResult.success(
            content="Health check passed",
            metadata=health_status
        )

    except Exception as e:
        return ToolResult.error(
            f"Health check failed: {str(e)}",
            metadata={"status": "unhealthy"}
        )
```

## Advanced Topics

### 1. Plugin Architecture

Create pluggable MCP servers:

```python
# plugin_base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BasePlugin(ABC):
    """Base class for MCP plugins."""

    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def get_tools(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def execute_tool(self, tool_name: str, **kwargs) -> Any:
        pass
```

### 2. Configuration Management

```python
# config.py
from pydantic import BaseSettings, Field
from typing import List, Optional

class MCPConfig(BaseSettings):
    """Configuration for MCP servers."""

    name: str = Field(..., description="Server name")
    version: str = Field(..., description="Server version")
    description: str = Field(..., description="Server description")

    # Rate limiting
    rate_limit: int = Field(100, description="Requests per minute")

    # Caching
    cache_enabled: bool = Field(True, description="Enable caching")
    cache_ttl: int = Field(300, description="Cache TTL in seconds")

    # Timeouts
    connect_timeout: int = Field(30, description="Connection timeout")
    read_timeout: int = Field(30, description="Read timeout")

    class Config:
        env_prefix = "MCP_"
```

### 3. Monitoring and Metrics

```python
# monitoring.py
from typing import Dict, Any
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ToolMetrics:
    """Metrics for tool execution."""
    name: str
    calls: int = 0
    total_time: float = 0.0
    errors: int = 0
    last_called: Optional[datetime] = None

    @property
    def average_time(self) -> float:
        return self.total_time / self.calls if self.calls > 0 else 0

    def record_call(self, duration: float, success: bool = True):
        self.calls += 1
        self.total_time += duration
        self.last_called = datetime.now()
        if not success:
            self.errors += 1

class MonitoredMCPServer(BaseMCPServer):
    """MCP server with monitoring capabilities."""

    def __init__(self):
        super().__init__()
        self.metrics: Dict[str, ToolMetrics] = {}

    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute tool with monitoring."""
        start_time = datetime.now()

        try:
            result = await super().execute_tool(tool_name, **kwargs)

            # Record metrics
            duration = (datetime.now() - start_time).total_seconds()
            if tool_name not in self.metrics:
                self.metrics[tool_name] = ToolMetrics(tool_name)

            self.metrics[tool_name].record_call(duration, result.success)

            return result

        except Exception as e:
            # Record error
            duration = (datetime.now() - start_time).total_seconds()
            if tool_name in self.metrics:
                self.metrics[tool_name].record_call(duration, False)

            raise
```

### 4. Dynamic Tool Registration

```python
class DynamicMCPServer(BaseMCPServer):
    """MCP server with dynamic tool registration."""

    def __init__(self):
        super().__init__()
        self.dynamic_tools = {}

    def register_dynamic_tool(self, tool_config: Dict[str, Any]) -> bool:
        """Register a tool at runtime."""
        try:
            tool_name = tool_config["name"]
            handler = tool_config["handler"]

            # Register with validation
            self.register_tool(
                name=tool_name,
                description=tool_config.get("description", ""),
                schema=tool_config.get("schema", {}),
                handler=handler
            )

            # Store reference for dynamic management
            self.dynamic_tools[tool_name] = tool_config

            return True

        except Exception as e:
            self.logger.error(f"Failed to register dynamic tool: {e}")
            return False

    async def handle_list_dynamic_tools(self, **kwargs) -> ToolResult:
        """List all dynamically registered tools."""
        tool_list = [
            {
                "name": name,
                "description": config.get("description", ""),
                "schema": config.get("schema", {})
            }
            for name, config in self.dynamic_tools.items()
        ]

        return ToolResult.success(
            content=f"Found {len(tool_list)} dynamic tools",
            metadata={"tools": tool_list}
        )
```

This development guide provides comprehensive coverage for MCP server development in AICMDEngine, from basic setup to advanced topics.