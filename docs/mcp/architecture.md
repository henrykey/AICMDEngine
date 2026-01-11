# MCP Architecture Documentation

This document provides a comprehensive overview of the MCP (Model Context Protocol) architecture in AICMDEngine, including design principles, component interactions, and implementation details.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Components](#core-components)
3. [Data Flow](#data-flow)
4. [Design Patterns](#design-patterns)
5. [Scalability Considerations](#scalability-considerations)
6. [Security Architecture](#security-architecture)
7. [Monitoring and Observability](#monitoring-and-observability)
8. [Extensibility Points](#extensibility-points)
9. [Future Enhancements](#future-enhancements)

## Architecture Overview

### System Architecture

The MCP framework follows a modular, service-oriented architecture that enables:

- **Separation of Concerns**: Each MCP server manages its own tools and business logic
- **Scalability**: Independent deployment and scaling of MCP servers
- **Extensibility**: Easy addition of new MCP servers and tools
- **Observability**: Comprehensive logging and monitoring capabilities

```
┌─────────────────────────────────────────────────────────────┐
│                    AICMDEngine Application                   │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │  Planning   │  │   LLM Management │  │   Command Sets  │ │
│  │    Engine   │  │                 │  │                 │ │
│  └─────────────┘  └─────────────────┘  └─────────────────┘ │
│           │                │                 │             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                   MCP Registry                         │ │
│  │ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │ │
│  │ │ Membership │ │ Test MCP    │ │ Custom MCP  │ ...   │ │
│  │ │   Server   │ │   Server    │ │   Server   │       │ │
│  │ └─────────────┘ └─────────────┘ └─────────────┘       │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                    External Services                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │
│  │  Membership │  │ Payments    │  │ Analytics      │    │
│  │     API     │  │     API     │  │     API        │    │
│  └─────────────┘  └─────────────┘  └─────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Loose Coupling**: Components interact through well-defined interfaces
2. **Single Responsibility**: Each MCP server focuses on a specific domain
3. **Async-First**: Built on asynchronous operations for better performance
4. **Error Resilience**: Graceful error handling and recovery mechanisms
5. **Developer Experience**: Simple APIs and comprehensive tooling

## Core Components

### 1. MCP Registry

The `MCPRegistry` serves as the central coordination point for all MCP servers.

#### Responsibilities

- **Server Registration**: Manages the lifecycle of MCP servers
- **Tool Discovery**: Provides centralized tool discovery and execution
- **Load Balancing**: Distributes tool execution across servers
- **Health Monitoring**: Tracks server status and availability

#### Key Methods

```python
class MCPRegistry:
    # Registration Management
    register_mcp(self, mcp: BaseMCPServer) -> None
    get_mcp(self, mcp_name: str) -> Optional[BaseMCPServer]
    remove_mcp(self, mcp_name: str) -> bool

    # Tool Execution
    async def execute_command(
        self,
        mcp_name: str,
        tool_name: str,
        **kwargs
    ) -> ToolResult

    # Lifecycle Management
    async def initialize_mcp(self, mcp_name: str) -> bool

    # Information Retrieval
    def get_registry_info(self) -> Dict[str, Any]
    def get_mcp_info(self, mcp_name: str) -> Optional[Dict[str, Any]]
```

#### Implementation Details

```python
class MCPRegistry:
    def __init__(self):
        self.mcps: Dict[str, BaseMCPServer] = {}
        self._lock = asyncio.Lock()  # Thread-safe operations

    async def execute_command(self, mcp_name: str, tool_name: str, **kwargs) -> ToolResult:
        async with self._lock:
            mcp = self.get_mcp(mcp_name)
            if not mcp:
                return ToolResult.error(f"MCP '{mcp_name}' not found")

            # Check server status
            if not mcp.is_initialized:
                # Auto-initialize if needed
                success = await self.initialize_mcp(mcp_name)
                if not success:
                    return ToolResult.error(f"Failed to initialize MCP '{mcp_name}'")

            return await mcp.execute_tool(tool_name, **kwargs)
```

### 2. BaseMCPServer

The `BaseMCPServer` abstract class provides the foundation for all MCP servers.

#### Core Features

- **Tool Management**: Registration and execution of tools
- **Lifecycle Management**: Initialization and shutdown procedures
- **Metadata Handling**: Version, author, and dependency information
- **Error Handling**: Consistent error response formatting

#### Class Structure

```python
class BaseMCPServer(ABC):
    # Basic Information
    name: str
    version: str
    description: str
    author: str

    # Runtime State
    is_initialized: bool = False
    last_heartbeat: Optional[datetime] = None
    start_time: Optional[datetime] = None

    # Tool Storage
    tools: Dict[str, 'Tool'] = {}

    def __init__(
        self,
        name: str,
        version: str,
        description: str,
        author: str = "Unknown",
        dependencies: List[str] = None
    ):
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.dependencies = dependencies or []
        self.tools = {}

    @abstractmethod
    async def register_tools(self) -> None:
        """Register all tools for this server."""
        pass

    def register_tool(
        self,
        name: str,
        description: str,
        schema: Dict[str, Any],
        handler: Callable
    ) -> None:
        """Register a tool with the server."""
        tool = Tool(
            name=name,
            description=description,
            schema=schema,
            handler=handler
        )
        self.tools[name] = tool

    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute a tool by name."""
        tool = self.tools.get(tool_name)
        if not tool:
            return ToolResult.error(f"Tool '{tool_name}' not found")

        try:
            # Validate input schema
            validation_result = self._validate_input(tool.schema, kwargs)
            if not validation_result.valid:
                return ToolResult.error(
                    f"Invalid input: {validation_result.error}",
                    error_code="INVALID_INPUT"
                )

            # Execute tool
            result = await tool.handler(**kwargs)

            # Ensure proper ToolResult format
            if not isinstance(result, ToolResult):
                result = ToolResult.success(
                    content=str(result),
                    metadata={}
                )

            return result

        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return ToolResult.error(str(e))

    async def initialize(self) -> None:
        """Initialize the MCP server."""
        if self.is_initialized:
            return

        try:
            # Register tools
            await self.register_tools()

            # Custom initialization logic
            await self._initialize_custom()

            self.is_initialized = True
            self.start_time = datetime.now()
            self.last_heartbeat = datetime.now()

            logger.info(f"MCP server '{self.name}' initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize MCP server '{self.name}': {e}")
            raise
```

### 3. Tool System

The Tool system handles tool registration, validation, and execution.

#### Tool Class

```python
@dataclass
class Tool:
    name: str
    description: str
    schema: Dict[str, Any]
    handler: Callable
    status: str = "active"
    metadata: Dict[str, Any] = None

    def get_info(self) -> Dict[str, Any]:
        """Get tool information for API documentation."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
            "status": self.status,
            "metadata": self.metadata or {}
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with provided arguments."""
        return await self.handler(**kwargs)
```

#### Input Validation

```python
class InputValidator:
    @staticmethod
    def validate_schema(schema: Dict[str, Any], data: Any) -> ValidationResult:
        """Validate data against JSON schema."""
        try:
            # Use jsonschema library for validation
            validate(instance=data, schema=schema)
            return ValidationResult(valid=True)
        except ValidationError as e:
            return ValidationResult(
                valid=False,
                error=str(e.message)
            )
        except Exception as e:
            return ValidationResult(
                valid=False,
                error=f"Validation error: {str(e)}"
            )
```

### 4. Management Interface

The React-based management interface provides real-time monitoring and control.

#### Architecture

```
┌─────────────────────────────────────────────────────┐
│                   React Frontend                     │
├─────────────────────────────────────────────────────┤
│ ┌───────────────┐  ┌─────────────────────┐          │
│ │  Server List  │  │   Server Details   │          │
│ │               │  │                     │          │
│ │ ┌───────────┐ │  │ ┌─────────────────┐ │          │
│ │ │ Server A  │ │  │ │  Configuration  │ │          │
│ │ │ Status    │ │  │ │   Overview    │ │          │
│ │ │ Health    │ │  │ │                 │ │          │
│ │ │ Actions   │ │  │ └─────────────────┘ │          │
│ │ └───────────┘ │  │ ┌─────────────────┐ │          │
│ │ ┌───────────┐ │  │ │   Tools List   │ │          │
│ │ │ Server B  │ │  │ │                 │ │          │
│ │ │ Status    │ │  │ └─────────────────┘ │          │
│ │ │ Health    │ │  └─────────────────────┘          │
│ │ │ Actions   │ │  ┌─────────────────────┐          │
│ │ └───────────┘ │  │   Real-time Updates  │          │
│ └───────────────┘  │   (WebSocket)      │          │
│ ┌───────────────┐  └─────────────────────┘          │
│ │   Dashboard  │                                    │
│ │   Overview    │                                    │
│ └───────────────┘                                    │
└─────────────────────────────────────────────────────┘
          │              │
          ▼              ▼
┌─────────────────────────────────────────────────────┐
│                   FastAPI Backend                     │
├─────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │
│  │   /v1/mcp/  │  │   /api/mcp/ │  │  WebSocket  │   │
│  │   REST API  │  │   Real-time │  │   Endpoint  │   │
│  │             │  │   Updates   │  │             │   │
│  └─────────────┘  └─────────────┘  └─────────────┘   │
└─────────────────────────────────────────────────────┘
```

#### Real-time Updates

```typescript
// WebSocket service for real-time updates
class MCPWebSocketService {
    private connections: Set<WebSocket> = new Set();
    private serverStatus: Map<string, ServerStatus> = new Map();

    addConnection(ws: WebSocket) {
        this.connections.add(ws);
        this.sendInitialStatus(ws);
    }

    broadcastUpdate(serverName: string, status: ServerStatus) {
        this.serverStatus.set(serverName, status);

        const update = {
            type: 'server_update',
            server: serverName,
            data: status
        };

        this.connections.forEach(ws => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify(update));
            }
        });
    }
}
```

## Data Flow

### Tool Execution Flow

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Client Request │    │   MCP Registry  │    │  MCP Server    │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│                 │    │                 │    │                 │
│ 1. Execute Tool │───▶│ 2. Find Server │───▶│ 3. Find Tool   │
│                 │    │                 │    │                 │
│ 2. Parameters   │    │ 4. Check Status │    │ 4. Validate    │
│                 │    │                 │    │   Input        │
│ 3. Tool Name    │    │ 5. Auto Init   │    │ 5. Execute     │
│                 │    │                 │    │   Handler      │
│                 │    │                 │    │                 │
│ 6. Get Result   │◀───│ 6. Return Result│◀───│ 6. Return      │
│                 │    │                 │    │   Result       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Detailed Flow Steps

1. **Client Request**: Client sends tool execution request via REST API
2. **Registry Lookup**: MCP Registry locates the appropriate server
3. **Status Check**: Registry checks if server is initialized
4. **Auto-initialization**: If needed, server is automatically initialized
5. **Tool Lookup**: MCP Server locates the requested tool
6. **Input Validation**: Input parameters are validated against schema
7. **Handler Execution**: Tool handler is called with validated parameters
8. **Result Processing**: Result is wrapped in ToolResponse format
9. **Response Return**: Response is returned through all layers

### Error Handling Flow

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Error Handler │    │    Registry     │    │   MCP Server    │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│                 │    │                 │    │                 │
│ 1. Client Error │    │ 2. Log Error    │    │ 3. Log Error    │
│                 │    │                 │    │                 │
│ 2. Error Code   │    │ 3. Error Code   │    │ 4. Error Code   │
│                 │    │                 │    │                 │
│ 3. Error Msg    │    │ 4. Error Msg    │    │ 5. Error Msg    │
│                 │    │                 │    │                 │
│ 4. Return       │◀───│ 5. Return       │◀───│ 6. Return       │
│   Response      │    │   Response      │    │   Response      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Design Patterns

### 1. Registry Pattern

Used for managing MCP servers and tool discovery.

```python
# Registry Implementation
class MCPRegistry:
    def __init__(self):
        self._servers: Dict[str, BaseMCPServer] = {}

    def register(self, server: BaseMCPServer) -> None:
        """Register a server instance."""
        self._servers[server.name] = server

    def get(self, name: str) -> Optional[BaseMCPServer]:
        """Retrieve a server by name."""
        return self._servers.get(name)

    def list_all(self) -> List[BaseMCPServer]:
        """List all registered servers."""
        return list(self._servers.values())
```

### 2. Strategy Pattern

Used for different tool execution strategies.

```python
# Execution Strategies
class ExecutionStrategy(ABC):
    @abstractmethod
    async def execute(self, tool: Tool, **kwargs) -> ToolResult:
        pass

class SyncExecutionStrategy(ExecutionStrategy):
    async def execute(self, tool: Tool, **kwargs) -> ToolResult:
        return tool.handler(**kwargs)

class AsyncExecutionStrategy(ExecutionStrategy):
    async def execute(self, tool: Tool, **kwargs) -> ToolResult:
        return await tool.handler(**kwargs)

class RetryExecutionStrategy(ExecutionStrategy):
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def execute(self, tool: Tool, **kwargs) -> ToolResult:
        for attempt in range(self.max_retries):
            try:
                return await tool.handler(**kwargs)
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

### 3. Observer Pattern

Used for server status updates and monitoring.

```python
# Observer Implementation
class ServerStatusObserver(ABC):
    @abstractmethod
    async def on_server_update(self, server_name: str, status: ServerStatus) -> None:
        pass

class LoggingObserver(ServerStatusObserver):
    async def on_server_update(self, server_name: str, status: ServerStatus) -> None:
        logger.info(f"Server {server_name} status changed to {status.status}")

class MetricsObserver(ServerStatusObserver):
    async def on_server_update(self, server_name: str, status: ServerStatus) -> None:
        # Update metrics
        self.metrics.counter("server.status", labels={"server": server_name})

class NotificationObserver(ServerStatusObserver):
    async def on_server_update(self, server_name: str, status: ServerStatus) -> None:
        if status.status == "error":
            # Send notification
            await self.notification_service.send_alert(
                f"Server {server_name} is in error state"
            )

class ObservableServer:
    def __init__(self):
        self._observers: List[ServerStatusObserver] = []

    def add_observer(self, observer: ServerStatusObserver) -> None:
        self._observers.append(observer)

    async def _notify_observers(self, status: ServerStatus) -> None:
        for observer in self._observers:
            await observer.on_server_update(self.name, status)
```

### 4. Factory Pattern

Used for creating MCP servers and tools.

```python
# MCP Server Factory
class MCPServerFactory:
    _servers = {
        'membership': 'MembershipMCPServer',
        'weather': 'WeatherMCPServer',
        'database': 'DatabaseMCPServer'
    }

    @classmethod
    def create_server(cls, server_type: str, **kwargs) -> BaseMCPServer:
        """Create an MCP server instance by type."""
        if server_type not in cls._servers:
            raise ValueError(f"Unknown server type: {server_type}")

        server_class = cls._servers[server_type]
        # Dynamically import and instantiate
        module = importlib.import_module(f"src.mcp_servers.{server_type}")
        return getattr(module, server_class)(**kwargs)

    @classmethod
    def list_available_servers(cls) -> List[str]:
        """List all available server types."""
        return list(cls._servers.keys())

# Tool Factory
class ToolFactory:
    @staticmethod
    def create_tool(tool_config: Dict[str, Any]) -> Tool:
        """Create a tool from configuration."""
        return Tool(
            name=tool_config['name'],
            description=tool_config['description'],
            schema=tool_config['schema'],
            handler=tool_config['handler'],
            status=tool_config.get('status', 'active')
        )
```

### 5. Decorator Pattern

Used for tool execution enhancements.

```python
# Tool Execution Decorators
def timeout_handler(timeout_seconds: int):
    """Decorator for adding timeout handling to tools."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                return ToolResult.error(
                    "Tool execution timeout",
                    error_code="TIMEOUT_ERROR"
                )
        return wrapper
    return decorator

def metrics_collector(func):
    """Decorator for collecting execution metrics."""
    async def wrapper(*args, **kwargs):
        start_time = time.time()

        try:
            result = await func(*args, **kwargs)

            duration = time.time() - start_time
            # Record metrics
            metrics.histogram("tool.execution_time", duration, labels={
                "server": args[0].name,
                "tool": func.__name__
            })
            metrics.counter("tool.executions", labels={
                "server": args[0].name,
                "tool": func.__name__,
                "status": "success"
            })

            return result

        except Exception as e:
            duration = time.time() - start_time
            metrics.histogram("tool.execution_time", duration, labels={
                "server": args[0].name,
                "tool": func.__name__
            })
            metrics.counter("tool.executions", labels={
                "server": args[0].name,
                "tool": func.__name__,
                "status": "error"
            })
            raise
    return wrapper

# Usage Example
class MyMCPServer(BaseMCPServer):
    async def register_tools(self) -> None:
        @timeout_handler(30)
        @metrics_collector
        async def handle_long_operation(self, **kwargs) -> ToolResult:
            # Long-running operation
            await asyncio.sleep(10)
            return ToolResult.success("Operation completed")

        self.register_tool(
            name="long_operation",
            description="Long running operation",
            schema={...},
            handler=handle_long_operation
        )
```

## Scalability Considerations

### 1. Horizontal Scaling

```python
# Load Balancing Strategy
class LoadBalancedMCPRegistry:
    def __init__(self):
        self._servers: Dict[str, List[BaseMCPServer]] = {}
        self._balancer = RoundRobinBalancer()

    def register_server(self, server: BaseMCPServer, group: str = "default") -> None:
        """Register a server in a group for load balancing."""
        if group not in self._servers:
            self._servers[group] = []
        self._servers[group].append(server)

    async def execute_command(self, mcp_name: str, tool_name: str, **kwargs) -> ToolResult:
        """Execute command with load balancing."""
        # Find all servers with the given name
        servers = []
        for group_server_list in self._servers.values():
            for server in group_server_list:
                if server.name == mcp_name:
                    servers.append(server)

        if not servers:
            return ToolResult.error(f"MCP '{mcp_name}' not found")

        # Select server using load balancer
        server = self._balancer.select(servers)

        # Execute on selected server
        return await server.execute_tool(tool_name, **kwargs)

class RoundRobinBalancer:
    def __init__(self):
        self._counter = 0

    def select(self, servers: List[BaseMCPServer]) -> BaseMCPServer:
        """Select server using round-robin algorithm."""
        server = servers[self._counter % len(servers)]
        self._counter += 1
        return server
```

### 2. Connection Pooling

```python
# Connection Pool for External APIs
class APIClient:
    def __init__(self, max_connections: int = 10):
        self.session_pool = asyncio.Queue(maxsize=max_connections)
        self._initialize_pool(max_connections)

    async def _initialize_pool(self, size: int) -> None:
        """Initialize connection pool."""
        for _ in range(size):
            session = aiohttp.ClientSession()
            await self.session_pool.put(session)

    async def get_session(self) -> aiohttp.ClientSession:
        """Get session from pool."""
        return await self.session_pool.get()

    async def release_session(self, session: aiohttp.ClientSession) -> None:
        """Return session to pool."""
        await self.session_pool.put(session)

    async def request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with connection pooling."""
        session = await self.get_session()
        try:
            async with session.request(method, url, **kwargs) as response:
                return await response.json()
        finally:
            await self.release_session(session)
```

### 3. Caching Layer

```python
# Multi-level Caching
class CacheManager:
    def __init__(self):
        self.memory_cache = {}
        self.redis_client = redis.Redis()

    async def get(self, key: str, cache_type: str = "memory") -> Optional[Any]:
        """Get value from cache."""
        if cache_type == "memory":
            return self.memory_cache.get(key)
        elif cache_type == "redis":
            value = await self.redis_client.get(key)
            return json.loads(value) if value else None

    async def set(self, key: str, value: Any, ttl: int, cache_type: str = "memory") -> None:
        """Set value in cache."""
        if cache_type == "memory":
            self.memory_cache[key] = {
                'value': value,
                'expires_at': time.time() + ttl
            }
        elif cache_type == "redis":
            await self.redis_client.setex(key, ttl, json.dumps(value))

    async def get_or_set(self, key: str, ttl: int, fetch_func: Callable, cache_type: str = "memory") -> Any:
        """Get from cache or fetch if not available."""
        cached_value = await self.get(key, cache_type)

        if cached_value and cache_type == "memory":
            # Check expiration
            if time.time() < cached_value['expires_at']:
                return cached_value['value']

        if cached_value and cache_type == "redis":
            # Redis handles TTL automatically
            return cached_value

        # Fetch and cache
        value = await fetch_func()
        await self.set(key, value, ttl, cache_type)
        return value
```

## Security Architecture

### 1. Input Validation

```python
# Comprehensive Input Validation
class InputValidator:
    @staticmethod
    def validate_tool_input(schema: Dict[str, Any], data: Any) -> ValidationResult:
        """Validate tool input with additional security checks."""
        # JSON Schema validation
        schema_validation = InputValidator.validate_schema(schema, data)
        if not schema_validation.valid:
            return schema_validation

        # Security validation
        security_result = InputValidator.validate_security(data)
        if not security_result.valid:
            return security_result

        return ValidationResult(valid=True)

    @staticmethod
    def validate_security(data: Any) -> ValidationResult:
        """Validate input for security issues."""
        if isinstance(data, dict):
            # Check for SQL injection patterns
            for key, value in data.items():
                if isinstance(value, str):
                    if SQL_INJECTION_PATTERN.search(value):
                        return ValidationResult(
                            valid=False,
                            error="Potential SQL injection detected"
                        )

                    # Check for XSS patterns
                    if XSS_PATTERN.search(value):
                        return ValidationResult(
                            valid=False,
                            error="Potential XSS detected"
                        )

                    # Check for path traversal
                    if ".." in value or "/" in value:
                        return ValidationResult(
                            valid=False,
                            error="Potential path traversal detected"
                        )

        return ValidationResult(valid=True)
```

### 2. Rate Limiting

```python
# Rate Limiting Implementation
class RateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.request_times = []
        self._lock = asyncio.Lock()

    async def is_allowed(self, identifier: str) -> bool:
        """Check if request is allowed based on rate limit."""
        async with self._lock:
            now = time.time()

            # Remove old requests (older than 1 minute)
            self.request_times = [
                req_time for req_time in self.request_times
                if now - req_time < 60
            ]

            # Check if limit exceeded
            if len(self.request_times) >= self.requests_per_minute:
                return False

            # Record this request
            self.request_times.append(now)
            return True

# Decorator for rate limiting
def rate_limit(requests_per_minute: int):
    """Decorator for rate limiting tool execution."""
    limiter = RateLimiter(requests_per_minute)

    def decorator(func):
        async def wrapper(*args, **kwargs):
            client_ip = kwargs.get('client_ip', 'unknown')
            if not await limiter.is_allowed(client_ip):
                return ToolResult.error(
                    "Rate limit exceeded",
                    error_code="RATE_LIMIT_EXCEEDED"
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

### 3. Authentication and Authorization

```python
# Security Middleware
class SecurityMiddleware:
    def __init__(self):
        self.api_keys = {}
        self.role_permissions = {}

    def register_api_key(self, api_key: str, permissions: List[str]) -> None:
        """Register an API key with permissions."""
        self.api_keys[api_key] = permissions

    async def authenticate(self, request: Request) -> AuthResult:
        """Authenticate request and check permissions."""
        # Extract API key
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return AuthResult(
                authenticated=False,
                error="API key required"
            )

        # Check if API key exists
        if api_key not in self.api_keys:
            return AuthResult(
                authenticated=False,
                error="Invalid API key"
            )

        return AuthResult(
            authenticated=True,
            permissions=self.api_keys[api_key]
        )

    async def authorize(self, request: Request, required_permission: str) -> bool:
        """Check if request has required permission."""
        auth_result = await self.authenticate(request)
        if not auth_result.authenticated:
            return False

        return required_permission in auth_result.permissions

# Usage in FastAPI
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Skip authentication for health checks
    if request.url.path.startswith("/v1/mcp/health"):
        return await call_next(request)

    security_middleware = SecurityMiddleware()

    # Check authentication
    auth_result = await security_middleware.authenticate(request)
    if not auth_result.authenticated:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error_message": auth_result.error,
                "error_code": "AUTH_REQUIRED"
            }
        )

    # Check authorization for specific endpoints
    if request.url.path.startswith("/v1/mcp/servers/"):
        required_permission = "server_management"
        if not await security_middleware.authorize(request, required_permission):
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error_message": "Insufficient permissions",
                    "error_code": "INSUFFICIENT_PERMISSIONS"
                }
            )

    response = await call_next(request)
    return response
```

## Monitoring and Observability

### 1. Logging Framework

```python
# Structured Logging
class StructuredLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        # Create structured formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(extra)s'
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def log_tool_execution(self, server_name: str, tool_name: str,
                          success: bool, duration: float,
                          error_message: str = None) -> None:
        """Log tool execution metrics."""
        extra = {
            "server": server_name,
            "tool": tool_name,
            "duration": duration,
            "success": success
        }

        if success:
            self.logger.info(f"Tool execution completed", extra=extra)
        else:
            self.logger.error(f"Tool execution failed: {error_message}", extra=extra)

    def log_server_status(self, server_name: str, status: str,
                         health_score: int = None) -> None:
        """Log server status changes."""
        extra = {
            "server": server_name,
            "status": status
        }

        if health_score is not None:
            extra["health_score"] = health_score

        self.logger.info(f"Server status updated", extra=extra)
```

### 2. Metrics Collection

```python
# Metrics Collection
class MetricsCollector:
    def __init__(self):
        self.metrics = {
            "tool_executions": Counter(),
            "tool_errors": Counter(),
            "server_uptime": Gauge(),
            "response_times": Histogram()
        }

    def record_tool_execution(self, server_name: str, tool_name: str,
                             success: bool, duration: float) -> None:
        """Record tool execution metrics."""
        labels = {
            "server": server_name,
            "tool": tool_name,
            "status": "success" if success else "error"
        }

        self.metrics["tool_executions"].labels(**labels).inc()

        if not success:
            self.metrics["tool_errors"].labels(**labels).inc()

        self.metrics["response_times"].labels(**labels).observe(duration)

    def record_server_health(self, server_name: str, health_score: int) -> None:
        """Record server health metrics."""
        self.metrics["server_uptime"].labels(server=server_name).set(health_score)

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get metrics summary."""
        return {
            name: metric.collect()
            for name, metric in self.metrics.items()
        }

# Prometheus Integration
class PrometheusMetrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.metrics = {
            "tool_executions": Counter(
                'tool_executions_total',
                'Total tool executions',
                ['server', 'tool', 'status'],
                registry=self.registry
            ),
            "response_time": Histogram(
                'tool_execution_seconds',
                'Tool execution time',
                ['server', 'tool'],
                registry=self.registry
            ),
            "server_health": Gauge(
                'server_health_score',
                'Server health score (0-100)',
                ['server'],
                registry=self.registry
            )
        }

    def record_execution(self, server: str, tool: str, success: bool, duration: float):
        """Record execution metrics."""
        labels = {'server': server, 'tool': tool}

        self.metrics['tool_executions'].labels(
            server=server,
            tool=tool,
            status='success' if success else 'error'
        ).inc()

        self.metrics['response_time'].labels(**labels).observe(duration)

    def record_health(self, server: str, health_score: int):
        """Record server health."""
        self.metrics['server_health'].labels(server=server).set(health_score)

    def generate_metrics(self) -> str:
        """Generate Prometheus metrics text."""
        return generate_latest(self.registry)
```

### 3. Distributed Tracing

```python
# Tracing Implementation
class Tracer:
    def __init__(self):
        self.tracer = trace.get_tracer("aicmdengine.mcp")

    def trace_tool_execution(self, server_name: str, tool_name: str):
        """Decorator for tracing tool execution."""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                with self.tracer.start_as_current_span(
                    f"mcp.{server_name}.{tool_name}"
                ) as span:
                    span.set_attribute("server.name", server_name)
                    span.set_attribute("tool.name", tool_name)
                    span.set_attribute("tool.start_time", time.time())

                    try:
                        result = await func(*args, **kwargs)
                        span.set_attribute("tool.success", True)
                        return result
                    except Exception as e:
                        span.set_attribute("tool.success", False)
                        span.set_attribute("tool.error", str(e))
                        raise
                    finally:
                        span.set_attribute("tool.end_time", time.time())
                        span.end()
            return wrapper
        return decorator

# Usage
class TracedMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__()
        self.tracer = Tracer()

    async def register_tools(self) -> None:
        @self.tracer.trace_tool_execution(self.name, "greet")
        async def handle_greet(self, **kwargs) -> ToolResult:
            # Tool implementation
            pass

        self.register_tool("greet", "Greet user", {...}, handle_greet)
```

## Extensibility Points

### 1. Custom MCP Server Creation

```python
# Base class for custom servers
class CustomMCPServer(BaseMCPServer):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(
            name=config["name"],
            version=config.get("version", "1.0.0"),
            description=config.get("description", "Custom MCP server"),
            author=config.get("author", "Unknown"),
            dependencies=config.get("dependencies", [])
        )
        self.config = config

    async def register_tools(self) -> None:
        # Override this method to register custom tools
        pass

    async def initialize_custom(self) -> None:
        """Override for custom initialization logic."""
        pass
```

### 2. Plugin System

```python
# Plugin loader
class PluginLoader:
    def __init__(self, plugin_directory: str = "src/mcp_servers"):
        self.plugin_directory = plugin_directory
        self.loaded_plugins = {}

    async def load_plugins(self) -> Dict[str, BaseMCPServer]:
        """Load all plugins from plugin directory."""
        for plugin_name in os.listdir(self.plugin_directory):
            plugin_path = os.path.join(self.plugin_directory, plugin_name)

            if os.path.isdir(plugin_path):
                await self._load_plugin(plugin_name)

        return self.loaded_plugins

    async def _load_plugin(self, plugin_name: str) -> None:
        """Load a single plugin."""
        try:
            # Import plugin module
            module_path = f"src.mcp_servers.{plugin_name}"
            module = importlib.import_module(module_path)

            # Look for server class
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and
                    issubclass(attr, BaseMCPServer) and
                    attr != BaseMCPServer):

                    # Instantiate and register
                    server_instance = attr()
                    self.loaded_plugins[server_instance.name] = server_instance
                    logger.info(f"Loaded plugin: {plugin_name}")
                    break

        except Exception as e:
            logger.error(f"Failed to load plugin {plugin_name}: {e}")
```

### 3. Tool Registry Extension

```python
# Extended tool registry
class ExtendedToolRegistry:
    def __init__(self):
        self.tools = {}
        self.categories = {}
        self.tags = {}

    def register_tool_with_metadata(
        self,
        server_name: str,
        tool: Tool,
        category: str = None,
        tags: List[str] = None
    ) -> None:
        """Register tool with additional metadata."""
        key = f"{server_name}.{tool.name}"
        self.tools[key] = {
            "tool": tool,
            "server": server_name,
            "category": category,
            "tags": tags or []
        }

        # Update categories
        if category:
            if category not in self.categories:
                self.categories[category] = []
            self.categories[category].append(key)

        # Update tags
        for tag in tags or []:
            if tag not in self.tags:
                self.tags[tag] = []
            self.tags[tag].append(key)

    def get_tools_by_category(self, category: str) -> List[Tool]:
        """Get tools by category."""
        tool_keys = self.categories.get(category, [])
        return [self.tools[key]["tool"] for key in tool_keys]

    def get_tools_by_tag(self, tag: str) -> List[Tool]:
        """Get tools by tag."""
        tool_keys = self.tags.get(tag, [])
        return [self.tools[key]["tool"] for key in tool_keys]

    def search_tools(self, query: str) -> List[Tool]:
        """Search tools by name or description."""
        results = []
        query_lower = query.lower()

        for key, tool_info in self.tools.items():
            tool = tool_info["tool"]
            if (query_lower in tool.name.lower() or
                query_lower in tool.description.lower()):
                results.append(tool)

        return results
```

## Future Enhancements

### 1. gRPC Support

```python
# Future gRPC implementation
class MCPGrpcService:
    async def ExecuteTool(
        self,
        request: ExecuteToolRequest,
        context: grpc.aio.ServicerContext
    ) -> ExecuteToolResponse:
        """Execute tool via gRPC."""
        try:
            result = await self.registry.execute_command(
                mcp_name=request.server_name,
                tool_name=request.tool_name,
                **request.parameters
            )

            return ExecuteToolResponse(
                success=result.success,
                content=result.content,
                metadata=result.metadata,
                error_code=result.error_code,
                error_message=result.error_message
            )
        except Exception as e:
            return ExecuteToolResponse(
                success=False,
                error_message=str(e)
            )
```

### 2. Event Streaming

```python
# Event streaming for real-time updates
class EventStream:
    def __init__(self):
        self.subscribers = set()

    async def subscribe(self, websocket: WebSocket):
        """Subscribe to events."""
        await websocket.accept()
        self.subscribers.add(websocket)

    async def unsubscribe(self, websocket: WebSocket):
        """Unsubscribe from events."""
        self.subscribers.discard(websocket)
        await websocket.close()

    async def publish(self, event: Event):
        """Publish event to all subscribers."""
        for websocket in self.subscribers:
            try:
                await websocket.send_json(event.dict())
            except:
                self.subscribers.discard(websocket)
```

### 3. Advanced Caching

```python
# Multi-level caching strategy
class AdvancedCacheManager:
    def __init__(self):
        self.local_cache = LRUCache(maxsize=1000)
        self.distributed_cache = RedisCache()
        self.memory_cache = MemoryCache()

    async def get(self, key: str) -> Any:
        """Get with multi-level cache fallback."""
        # Try local cache first
        value = self.local_cache.get(key)
        if value is not None:
            return value

        # Try distributed cache
        value = await self.distributed_cache.get(key)
        if value is not None:
            # Warm up local cache
            self.local_cache[key] = value
            return value

        # Try memory cache
        value = await self.memory_cache.get(key)
        if value is not None:
            return value

        return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Set in all cache levels."""
        await self.local_cache.set(key, value, ttl)
        await self.distributed_cache.set(key, value, ttl)
        await self.memory_cache.set(key, value, ttl)
```

This architecture documentation provides a comprehensive view of the MCP framework's design, implementation patterns, and scalability considerations. The modular architecture allows for easy extension and customization while maintaining high performance and reliability.