# MCP Router API 使用指南

**版本**: 1.0
**最后更新**: 2026-02-08

---

## 目录

1. [快速开始](#快速开始)
2. [协议说明](#协议说明)
3. [认证方式](#认证方式)
4. [API端点](#api端点)
5. [消息格式](#消息格式)
6. [客户端集成](#客户端集成)
7. [完整示例](#完整示例)
8. [错误处理](#错误处理)
9. [最佳实践](#最佳实践)

---

## 快速开始

### 1分钟连接示例

```python
import jwt
import asyncio
import websockets
import json

# 生成JWT token
token = jwt.encode(
    {
        "sub": "my-app",
        "name": "My Application",
        "scopes": ["mcp:*"],
        "exp": 1735689600  # 设置合适的过期时间
    },
    "your-secret-key"
)

# 连接到MCP Router
async def connect_and_call_tools():
    uri = "ws://localhost:8000/mcp/v1"
    async with websockets.connect(f"{uri}?token={token}") as ws:
        # 1. 初始化握手
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "my-app",
                    "version": "1.0.0"
                }
            }
        }))

        response = await ws.recv()
        print("Server:", response)

        # 2. 获取工具列表
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }))

        response = await ws.recv()
        tools = json.loads(response)["result"]["tools"]
        print(f"Available tools: {len(tools)}")

        # 3. 调用工具
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "membership.list_members",
                "arguments": {
                    "page": 1,
                    "limit": 10
                }
            }
        }))

        response = await ws.recv()
        result = json.loads(response)["result"]
        print("Tool result:", result)

asyncio.run(connect_and_call_tools())
```

---

## 协议说明

### MCP协议简介

MCP (Model Context Protocol) 是基于JSON-RPC 2.0的协议，用于LLM应用访问工具、资源和提示词。

### 核心特性

- ✅ **JSON-RPC 2.0** - 标准的请求-响应协议
- ✅ **双向通信** - 通过WebSocket实现实时通信
- ✅ **类型安全** - 结构化的输入输出schema
- ✅ **可扩展** - 支持自定义工具和资源

### 消息模型

所有消息遵循JSON-RPC 2.0格式：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "method_name",
  "params": { }
}
```

---

## 认证方式

### JWT Token要求

MCP Router要求JWT token包含以下信息：

```json
{
  "sub": "client-unique-id",           // 必需：客户端唯一标识
  "name": "Client Display Name",        // 可选：客户端显示名称
  "scopes": ["mcp:*", "api:read"],     // 必需：权限scope
  "permissions": ["mcp.access"],       // 可选：权限列表
  "exp": 1735689600,                   // 必需：过期时间戳
  "iat": 1735686000,                   // 可选：签发时间
  "tenant_id": 1                       // 可选：租户ID
}
```

### 权限scope格式

支持多种格式（满足其一即可）：

**方式1: scopes字段**
```json
{
  "scopes": ["mcp:*"]        // 完全访问
  // 或
  "scopes": ["mcp.read"]     // 只读访问
  // 或
  "scopes": ["mcp.tools.execute"]  // 工具执行权限
}
```

**方式2: permissions字段**
```json
{
  "permissions": ["mcp.access", "mcp.tools.execute"]
}
```

**方式3: resource_access (Keycloak风格)**
```json
{
  "resource_access": {
    "mcp": {
      "roles": ["admin"]
    }
  }
}
```

### Token生成示例

**Python (PyJWT)**
```python
import jwt
import time

payload = {
    "sub": "my-app-client",
    "name": "My Application",
    "scopes": ["mcp:*"],
    "exp": int(time.time()) + 3600,  # 1小时后过期
    "iat": int(time.time()),
    "tenant_id": 1
}

token = jwt.encode(payload, "your-secret-key", algorithm="HS256")
print(token)
```

**Node.js (jsonwebtoken)**
```javascript
const jwt = require('jsonwebtoken');

const payload = {
    sub: 'my-app-client',
    name: 'My Application',
    scopes: ['mcp:*'],
    exp: Math.floor(Date.now() / 1000) + 3600,
    iat: Math.floor(Date.now() / 1000),
    tenant_id: 1
};

const token = jwt.sign(payload, 'your-secret-key', { algorithm: 'HS256' });
console.log(token);
```

**Go (golang-jwt)**
```go
package main

import (
    "github.com/golang-jwt/jwt/v5"
    "time"
)

func generateToken() (string, error) {
    payload := jwt.MapClaims{
        "sub": "my-app-client",
        "name": "My Application",
        "scopes": []string{"mcp:*"},
        "exp": time.Now().Add(time.Hour).Unix(),
        "iat": time.Now().Unix(),
        "tenant_id": float64(1),
    }

    return jwt.NewWithClaims(jwt.SigningMethodHS256, payload).
        SignedString([]byte("your-secret-key"))
}
```

**Java (jjwt)**
```java
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.SignatureAlgorithm;
import java.util.Date;
import java.util.HashMap;
import java.util.Map;

Map<String, Object> claims = new HashMap<>();
claims.put("sub", "my-app-client");
claims.put("name", "My Application");
claims.put("scopes", new String[]{"mcp:*"});
claims.put("exp", new Date(System.currentTimeMillis() + 3600000));
claims.put("iat", new Date());
claims.put("tenant_id", 1);

String token = Jwts.builder()
    .setClaims(claims)
    .signWith(SignatureAlgorithm.HS256, "your-secret-key".getBytes())
    .compact();
```

---

## API端点

### WebSocket端点

**URL**: `ws://localhost:8000/mcp/v1` 或 `wss://your-domain.com/mcp/v1`

**连接参数**:
- `token` (query参数) - JWT token
- 或通过 `Authorization: Bearer <token>` header

**示例**:
```bash
# Query参数方式
ws://localhost:8000/mcp/v1?token=eyJhbGc...

# Header方式
Sec-WebSocket-Protocol: jwt-token
Authorization: Bearer eyJhbGc...
```

### 健康检查端点

**URL**: `GET http://localhost:8000/health`

**响应**:
```json
{
  "status": "ok",
  "service": "NL-TPS",
  "model": "deepseek-chat"
}
```

---

## 消息格式

### 1. Initialize 握手

**请求**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {
      "name": "my-app",
      "version": "1.0.0"
    }
  }
}
```

**响应**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {
      "name": "AICMDEngine MCP Router",
      "version": "1.0.0"
    },
    "capabilities": {
      "tools": {},
      "resources": {},
      "prompts": {}
    }
  }
}
```

### 2. Tools/List - 列出可用工具

**请求**:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list"
}
```

**响应**:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "membership.list_members",
        "description": "List all members in the organization",
        "inputSchema": {
          "type": "object",
          "properties": {
            "page": {
              "type": "integer",
              "description": "Page number",
              "default": 1
            },
            "limit": {
              "type": "integer",
              "description": "Items per page",
              "default": 10
            }
          }
        }
      },
      {
        "name": "membership.create_member",
        "description": "Create a new member",
        "inputSchema": {
          "type": "object",
          "properties": {
            "username": {
              "type": "string",
              "description": "Username"
            },
            "email": {
              "type": "string",
              "description": "Email address"
            }
          },
          "required": ["username", "email"]
        }
      }
    ]
  }
}
```

### 3. Tools/Call - 调用工具

**请求**:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "membership.list_members",
    "arguments": {
      "page": 1,
      "limit": 10
    }
  }
}
```

**响应**:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Found 10 members:\n1. John Doe (john@example.com)\n2. Jane Smith (jane@example.com)\n..."
      }
    ],
    "isError": false
  }
}
```

**错误响应**:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {
    "code": -32603,
    "message": "Internal error",
    "data": "Detailed error message"
  }
}
```

---

## 客户端集成

### Python客户端

**使用websockets库**

```python
import asyncio
import websockets
import json
import jwt
from typing import Any, Dict, List

class MCPClient:
    """MCP Router客户端"""

    def __init__(
        self,
        ws_url: str = "ws://localhost:8000/mcp/v1",
        jwt_secret: str = "your-secret-key",
        client_id: str = "python-client",
        client_name: str = "Python MCP Client"
    ):
        self.ws_url = ws_url
        self.jwt_secret = jwt_secret
        self.client_id = client_id
        self.client_name = client_name
        self.ws = None
        self.request_id = 0

    def _generate_token(self) -> str:
        """生成JWT token"""
        payload = {
            "sub": self.client_id,
            "name": self.client_name,
            "scopes": ["mcp:*"],
            "exp": int(asyncio.get_event_loop().time()) + 3600
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    async def connect(self):
        """连接到MCP Router"""
        token = self._generate_token()
        uri = f"{self.ws_url}?token={token}"

        self.ws = await websockets.connect(uri)

        # 初始化握手
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": self.client_name,
                "version": "1.0.0"
            }
        })

        response = await self._receive_response()
        print(f"Connected to: {response['result']['serverInfo']['name']}")

    async def get_tools(self) -> List[Dict[str, Any]]:
        """获取所有可用工具"""
        await self._send_request("tools/list", {})
        response = await self._receive_response()
        return response["result"]["tools"]

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> str:
        """调用工具"""
        await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        response = await self._receive_response()

        if "error" in response:
            raise Exception(f"Tool error: {response['error']}")

        return response["result"]["content"][0]["text"]

    async def _send_request(self, method: str, params: Dict[str, Any]):
        """发送请求"""
        self.request_id += 1

        message = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params
        }

        await self.ws.send(json.dumps(message))

    async def _receive_response(self) -> Dict[str, Any]:
        """接收响应"""
        response = await self.ws.recv()
        return json.loads(response)

    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()

# 使用示例
async def main():
    client = MCPClient(
        ws_url="ws://localhost:8000/mcp/v1",
        jwt_secret="your-secret-key"
    )

    try:
        await client.connect()

        # 获取工具列表
        tools = await client.get_tools()
        print(f"Available tools: {len(tools)}")
        for tool in tools[:5]:
            print(f"  - {tool['name']}: {tool['description']}")

        # 调用工具
        result = await client.call_tool(
            "membership.list_members",
            {"page": 1, "limit": 5}
        )
        print(f"\nTool result:\n{result}")

    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### JavaScript/TypeScript客户端

**使用WebSocket API**

```typescript
class MCPClient {
  private ws: WebSocket | null = null;
  private requestId = 0;
  private pendingRequests = new Map<number, (response: any) => void>();

  constructor(
    private wsUrl: string,
    private token: string,
    private clientInfo: { name: string; version: string }
  ) {}

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(`${this.wsUrl}?token=${this.token}`);

      this.ws.onopen = async () => {
        try {
          // 初始化握手
          await this.sendRequest("initialize", {
            protocolVersion: "2024-11-05",
            capabilities: {},
            clientInfo: this.clientInfo
          });

          const response = await this.receiveResponse();
          console.log("Connected to:", response.result.serverInfo.name);

          // 设置消息处理
          this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            const callback = this.pendingRequests.get(data.id);
            if (callback) {
              callback(data);
            }
          };

          resolve();
        } catch (error) {
          reject(error);
        }
      };

      this.ws.onerror = (error) => {
        reject(error);
      };
    });
  }

  async getTools(): Promise<any[]> {
    await this.sendRequest("tools/list", {});
    const response = await this.receiveResponse();
    return response.result.tools;
  }

  async callTool(toolName: string, arguments: Record<string, any>): Promise<string> {
    await this.sendRequest("tools/call", {
      name: toolName,
      arguments: arguments
    });

    const response = await this.receiveResponse();

    if (response.error) {
      throw new Error(`Tool error: ${response.error.message}`);
    }

    return response.result.content[0].text;
  }

  private async sendRequest(method: string, params: any): Promise<number> {
    return new Promise((resolve) => {
      this.requestId++;
      const id = this.requestId;

      const message = {
        jsonrpc: "2.0",
        id: id,
        method: method,
        params: params
      };

      this.ws!.send(JSON.stringify(message));
      resolve(id);
    });
  }

  private async receiveResponse(): Promise<any> {
    return new Promise((resolve) => {
      this.pendingRequests.set(this.requestId, resolve);
    });
  }

  async close(): Promise<void> {
    if (this.ws) {
      this.ws.close();
    }
  }
}

// 使用示例
async function main() {
  const client = new MCPClient(
    "ws://localhost:8000/mcp/v1",
    "your-jwt-token",
    { name: "TypeScript Client", version: "1.0.0" }
  );

  try {
    await client.connect();

    // 获取工具列表
    const tools = await client.getTools();
    console.log(`Available tools: ${tools.length}`);
    tools.slice(0, 5).forEach(tool => {
      console.log(`  - ${tool.name}: ${tool.description}`);
    });

    // 调用工具
    const result = await client.callTool("membership.list_members", {
      page: 1,
      limit: 5
    });

    console.log("\nTool result:");
    console.log(result);

  } finally {
    await client.close();
  }
}

main().catch(console.error);
```

### Go客户端

**使用gorilla/websocket**

```go
package main

import (
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "sync"

    "github.com/gorilla/websocket"
)

type MCPClient struct {
    wsUrl      string
    token      string
    conn       *websocket.Conn
    mutex      sync.Mutex
    requestID  int
    pending    map[int] chan []byte
}

type MCPMessage struct {
    JSONRPC string      `json:"jsonrpc"`
    ID      int         `json:"id"`
    Method  string      `json:"method,omitempty"`
    Params  interface{} `json:"params,omitempty"`
    Result  interface{} `json:"result,omitempty"`
    Error   interface{} `json:"error,omitempty"`
}

func NewMCPClient(wsUrl, token string) *MCPClient {
    return &MCPClient{
        wsUrl:   wsUrl,
        token:   token,
        pending: make(map[int] chan []byte),
    }
}

func (c *MCPClient) Connect() error {
    ws, _, err := websocket.DefaultDialer.Dial(
        c.wsUrl+"?token="+c.token,
        nil,
    )
    if err != nil {
        return err
    }

    c.conn = ws

    // 启动消息处理
    go c.handleMessages()

    // 初始化握手
    var response MCPMessage
    err = c.call("initialize", map[string]interface{}{
        "protocolVersion": "2024-11-05",
        "capabilities":    map[string]interface{}{},
        "clientInfo": map[string]interface{}{
            "name":    "Go Client",
            "version": "1.0.0",
        },
    }, &response)

    if err != nil {
        return err
    }

    serverInfo := response.Result.(map[string]interface{})["serverInfo"].(map[string]interface{})
    fmt.Printf("Connected to: %s\n", serverInfo["name"])

    return nil
}

func (c *MCPClient) GetTools() ([]interface{}, error) {
    var response MCPMessage
    err := c.call("tools/list", map[string]interface{}{}, &response)
    if err != nil {
        return nil, err
    }

    result := response.Result.(map[string]interface{})
    tools := result["tools"].([]interface{})

    return tools, nil
}

func (c *MCPClient) CallTool(toolName string, arguments map[string]interface{}) (string, error) {
    params := map[string]interface{}{
        "name":      toolName,
        "arguments": arguments,
    }

    var response MCPMessage
    err := c.call("tools/call", params, &response)
    if err != nil {
        return "", err
    }

    if response.Error != nil {
        return "", fmt.Errorf("tool error: %v", response.Error)
    }

    result := response.Result.(map[string]interface{})
    content := result["content"].([]interface{})
    firstContent := content[0].(map[string]interface{})
    text := firstContent["text"].(string)

    return text, nil
}

func (c *MCPClient) call(method string, params interface{}, response *MCPMessage) error {
    c.mutex.Lock()
    c.requestID++
    id := c.requestID

    responseChan := make(chan []byte, 1)
    c.pending[id] = responseChan
    c.mutex.Unlock()

    message := MCPMessage{
        JSONRPC: "2.0",
        ID:      id,
        Method:  method,
        Params:  params,
    }

    data, err := json.Marshal(message)
    if err != nil {
        return err
    }

    err = c.conn.WriteMessage(websocket.TextMessage, data)
    if err != nil {
        return err
    }

    // 等待响应
    respData := <-responseChan
    return json.Unmarshal(respData, response)
}

func (c *MCPClient) handleMessages() {
    for {
        _, message, err := c.conn.ReadMessage()
        if err != nil {
            log.Printf("Read error: %v", err)
            return
        }

        var data MCPMessage
        if err := json.Unmarshal(message, &data); err != nil {
            log.Printf("Parse error: %v", err)
            continue
        }

        c.mutex.Lock()
        if ch, ok := c.pending[data.ID]; ok {
            ch <- message
            delete(c.pending, data.ID)
        }
        c.mutex.Unlock()
    }
}

func (c *MCPClient) Close() {
    if c.conn != nil {
        c.conn.Close()
    }
}

// 使用示例
func main() {
    client := NewMCPClient(
        "ws://localhost:8000/mcp/v1",
        "your-jwt-token",
    )

    if err := client.Connect(); err != nil {
        log.Fatal("Connect error:", err)
    }
    defer client.Close()

    // 获取工具列表
    tools, err := client.GetTools()
    if err != nil {
        log.Fatal("Get tools error:", err)
    }

    fmt.Printf("Available tools: %d\n", len(tools))
    for i, tool := range tools {
        if i >= 5 {
            break
        }
        t := tool.(map[string]interface{})
        fmt.Printf("  - %s: %s\n", t["name"], t["description"])
    }

    // 调用工具
    result, err := client.CallTool("membership.list_members", map[string]interface{}{
        "page":   1,
        "limit": 5,
    })

    if err != nil {
        log.Fatal("Call tool error:", err)
    }

    fmt.Printf("\nTool result:\n%s\n", result)
}
```

### Rust客户端

**使用tokio-tungstenite**

```rust
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio_tungstenite::connect_async;

#[derive(Debug, Serialize, Deserialize)]
struct MCPMessage {
    jsonrpc: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    method: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    params: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<Value>,
}

struct MCPClient {
    url: String,
    token: String,
    request_id: i32,
}

impl MCPClient {
    fn new(url: &str, token: &str) -> Self {
        Self {
            url: url.to_string(),
            token: token.to_string(),
            request_id: 0,
        }
    }

    async fn connect(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        let url = format!("{}?token={}", self.url, self.token);
        let (mut ws, _) = connect_async(url).await?;

        // 初始化握手
        let init_msg = MCPMessage {
            jsonrpc: "2.0".to_string(),
            id: Some(1),
            method: Some("initialize".to_string()),
            params: Some(json!({
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "Rust Client",
                    "version": "1.0.0"
                }
            })),
            result: None,
            error: None,
        };

        let msg_str = serde_json::to_string(&init_msg)?;
        ws.send(tokio_tungstenite::tungstenite::Message::Text(msg_str)).await?;

        // 接收响应
        if let Some(msg) = ws.next().await {
            match msg {
                tokio_tungstenite::tungstenite::Message::Text(text) => {
                    let response: MCPMessage = serde_json::from_str(&text)?;
                    println!("Connected to: {:?}", response.result);
                }
                _ => {}
            }
        }

        Ok(())
    }

    async fn get_tools(&mut self) -> Result<Vec<Value>, Box<dyn std::error::Error>> {
        let msg = MCPMessage {
            jsonrpc: "2.0".to_string(),
            id: Some(2),
            method: Some("tools/list".to_string()),
            params: None,
            result: None,
            error: None,
        };

        // 发送请求...
        // 接收响应...

        Ok(vec![])
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut client = MCPClient::new(
        "ws://localhost:8000/mcp/v1",
        "your-jwt-token"
    );

    client.connect().await?;

    let tools = client.get_tools().await?;
    println!("Available tools: {}", tools.len());

    Ok(())
}
```

### Java客户端

**使用Java-WebSocket和Gson**

```java
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.reflect.TypeToken;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;

import java.net.URI;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * MCP Router客户端 - Java实现
 */
public class MCPClient extends WebSocketClient {
    private final Gson gson = new Gson();
    private final AtomicInteger requestId = new AtomicInteger(0);
    private final Map<Integer, CompletableFuture<JsonObject>> pendingRequests = new ConcurrentHashMap<>();
    private final String token;

    public MCPClient(String serverUri, String token) throws Exception {
        super(new URI(serverUri + "?token=" + token));
        this.token = token;
        this.setConnectionLostTimeout(0); // 禁用超时断开
    }

    @Override
    public void onOpen(ServerHandshake handshakedata) {
        System.out.println("WebSocket连接已建立");
    }

    @Override
    public void onMessage(String message) {
        JsonObject response = gson.fromJson(message, JsonObject.class);

        if (response.has("id")) {
            int id = response.get("id").getAsInt();
            CompletableFuture<JsonObject> future = pendingRequests.remove(id);
            if (future != null) {
                future.complete(response);
            }
        }
    }

    @Override
    public void onClose(int code, String reason, boolean remote) {
        System.out.println("WebSocket连接已关闭: " + reason);
    }

    @Override
    public void onError(Exception ex) {
        ex.printStackTrace();
    }

    /**
     * 初始化握手
     */
    public void initialize() throws Exception {
        JsonObject params = new JsonObject();
        params.addProperty("protocolVersion", "2024-11-05");

        JsonObject capabilities = new JsonObject();
        params.add("capabilities", capabilities);

        JsonObject clientInfo = new JsonObject();
        clientInfo.addProperty("name", "Java MCP Client");
        clientInfo.addProperty("version", "1.0.0");
        params.add("clientInfo", clientInfo);

        JsonObject response = sendRequest("initialize", params);

        if (response.has("error")) {
            throw new RuntimeException("Initialize failed: " + response.get("error"));
        }

        JsonObject result = response.getAsJsonObject("result");
        JsonObject serverInfo = result.getAsJsonObject("serverInfo");
        System.out.println("Connected to: " + serverInfo.get("name").getAsString());
    }

    /**
     * 获取所有可用工具
     */
    public ToolListResult getTools() throws Exception {
        JsonObject response = sendRequest("tools/list", null);

        if (response.has("error")) {
            throw new RuntimeException("Get tools failed: " + response.get("error"));
        }

        return gson.fromJson(
            response.getAsJsonObject("result").toString(),
            ToolListResult.class
        );
    }

    /**
     * 调用工具
     */
    public ToolCallResult callTool(String toolName, Map<String, Object> arguments) throws Exception {
        JsonObject params = new JsonObject();
        params.addProperty("name", toolName);
        params.add("arguments", gson.toJsonTree(arguments));

        JsonObject response = sendRequest("tools/call", params);

        if (response.has("error")) {
            JsonObject error = response.getAsJsonObject("error");
            throw new RuntimeException(
                "Tool error: " + error.get("message").getAsString()
            );
        }

        return gson.fromJson(
            response.getAsJsonObject("result").toString(),
            ToolCallResult.class
        );
    }

    /**
     * 发送请求并等待响应
     */
    private JsonObject sendRequest(String method, JsonObject params) throws Exception {
        int id = requestId.incrementAndGet();

        JsonObject request = new JsonObject();
        request.addProperty("jsonrpc", "2.0");
        request.addProperty("id", id);
        request.addProperty("method", method);
        if (params != null) {
            request.add("params", params);
        }

        CompletableFuture<JsonObject> future = new CompletableFuture<>();
        pendingRequests.put(id, future);

        send(gson.toJson(request));

        return future.get(); // 阻塞等待响应
    }

    // 工具列表结果
    public static class ToolListResult {
        public java.util.List<Tool> tools;
    }

    // 工具定义
    public static class Tool {
        public String name;
        public String description;
        public JsonObject inputSchema;
    }

    // 工具调用结果
    public static class ToolCallResult {
        public java.util.List<ContentItem> content;
        public boolean isError;
    }

    // 内容项
    public static class ContentItem {
        public String type;
        public String text;
    }

    // 使用示例
    public static void main(String[] args) {
        try {
            // 创建客户端
            MCPClient client = new MCPClient(
                "ws://localhost:8000/mcp/v1",
                "your-jwt-token"
            );

            // 连接到服务器
            client.connect();
            Thread.sleep(1000); // 等待连接建立

            // 初始化握手
            client.initialize();

            // 获取工具列表
            ToolListResult tools = client.getTools();
            System.out.println("Available tools: " + tools.tools.size());

            for (int i = 0; i < Math.min(5, tools.tools.size()); i++) {
                Tool tool = tools.tools.get(i);
                System.out.println("  - " + tool.name + ": " + tool.description);
            }

            // 调用工具
            Map<String, Object> arguments = Map.of(
                "page", 1,
                "limit", 5
            );

            ToolCallResult result = client.callTool("membership.list_members", arguments);

            System.out.println("\nTool result:");
            for (ContentItem item : result.content) {
                System.out.println(item.text);
            }

            // 关闭连接
            client.close();

        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}
```

**Maven依赖**:

```xml
<dependencies>
    <!-- WebSocket客户端 -->
    <dependency>
        <groupId>org.java-websocket</groupId>
        <artifactId>Java-WebSocket</artifactId>
        <version>1.5.4</version>
    </dependency>

    <!-- JSON处理 -->
    <dependency>
        <groupId>com.google.code.gson</groupId>
        <artifactId>gson</artifactId>
        <version>2.10.1</version>
    </dependency>
</dependencies>
```

**Gradle依赖**:

```gradle
dependencies {
    implementation 'org.java-websocket:Java-WebSocket:1.5.4'
    implementation 'com.google.code.gson:gson:2.10.1'
}
```

**Spring Boot集成示例**:

```java
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Value;
import javax.annotation.PostConstruct;
import javax.annotation.PreDestroy;

@Service
public class MCPService {
    @Value("${mcp.router.url:ws://localhost:8000/mcp/v1}")
    private String mcpRouterUrl;

    @Value("${mcp.jwt.secret:your-secret-key}")
    private String jwtSecret;

    private MCPClient mcpClient;

    @PostConstruct
    public void init() throws Exception {
        String token = generateJWTToken();
        mcpClient = new MCPClient(mcpRouterUrl, token);
        mcpClient.connect();
        Thread.sleep(1000);
        mcpClient.initialize();
    }

    @PreDestroy
    public void cleanup() {
        if (mcpClient != null) {
            mcpClient.close();
        }
    }

    public String listMembers(int page, int limit) {
        try {
            Map<String, Object> args = Map.of("page", page, "limit", limit);
            ToolCallResult result = mcpClient.callTool("membership.list_members", args);
            return result.content.get(0).text;
        } catch (Exception e) {
            throw new RuntimeException("Failed to list members", e);
        }
    }

    private String generateJWTToken() {
        // 使用io.jsonwebtoken生成JWT
        io.jsonwebtoken.Jwts.builder()
            .setSubject("spring-boot-app")
            .claim("name", "Spring Boot MCP Client")
            .claim("scopes", new String[]{"mcp:*"})
            .setExpiration(new java.util.Date(System.currentTimeMillis() + 3600000))
            .signWith(io.jsonwebtoken.SignatureAlgorithm.HS256, jwtSecret.getBytes())
            .compact();
    }
}
```

---

## 完整示例

### 示例1：构建MCP工具包装器

```python
"""
MCP工具包装器示例 - 将MCP工具包装为Python函数
"""

import asyncio
import json
from typing import Any, Dict, List
from mcp_client import MCPClient

class MembershipTools:
    """Membership API工具包装器"""

    def __init__(self, client: MCPClient):
        self.client = client

    async def list_members(
        self,
        page: int = 1,
        limit: int = 10
    ) -> str:
        """列出成员"""
        return await self.client.call_tool(
            "membership.list_members",
            {"page": page, "limit": limit}
        )

    async def get_member(self, member_id: str) -> str:
        """获取成员详情"""
        return await self.client.call_tool(
            "membership.get_member",
            {"member_id": member_id}
        )

    async def create_member(
        self,
        username: str,
        email: str,
        password: str
    ) -> str:
        """创建成员"""
        return await self.client.call_tool(
            "membership.create_member",
            {
                "username": username,
                "email": email,
                "password": password
            }
        )

    async def list_orgs(
        self,
        page: int = 1,
        limit: int = 10
    ) -> str:
        """列出组织"""
        return await self.client.call_tool(
            "membership.list_orgs",
            {"page": page, "limit": limit}
        )

# 使用示例
async def main():
    client = MCPClient(
        ws_url="ws://localhost:8000/mcp/v1",
        jwt_secret="your-secret-key"
    )

    try:
        await client.connect()

        tools = MembershipTools(client)

        # 列出成员
        members = await tools.list_members(page=1, limit=5)
        print("Members:", members)

        # 创建成员
        result = await tools.create_member(
            username="newuser",
            email="newuser@example.com",
            password="password123"
        )
        print("Create result:", result)

    finally:
        await client.close()

asyncio.run(main())
```

### 示例2：批量工具调用

```python
async def batch_process(client: MCPClient, operations: List[Dict]):
    """批量处理多个工具调用"""

    results = []

    for op in operations:
        try:
            result = await client.call_tool(
                op["tool"],
                op.get("arguments", {})
            )
            results.append({
                "operation": op["tool"],
                "status": "success",
                "result": result
            })
        except Exception as e:
            results.append({
                "operation": op["tool"],
                "status": "error",
                "error": str(e)
            })

    return results

async def main():
    client = MCPClient(
        ws_url="ws://localhost:8000/mcp/v1",
        jwt_secret="your-secret-key"
    )

    await client.connect()

    operations = [
        {"tool": "membership.list_members", "arguments": {"page": 1}},
        {"tool": "membership.list_orgs", "arguments": {"page": 1}},
        {"tool": "membership.list_roles", "arguments": {}},
    ]

    results = await batch_process(client, operations)

    for r in results:
        print(f"{r['operation']}: {r['status']}")
        if r['status'] == 'error':
            print(f"  Error: {r['error']}")
        else:
            print(f"  Result: {r['result'][:100]}...")

    await client.close()
```

### 示例3：错误处理和重试

```python
import asyncio
from mcp_client import MCPClient

class ResilientMCPClient(MCPClient):
    """带错误处理和重试的MCP客户端"""

    async def call_tool_with_retry(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> str:
        """带重试的工具调用"""

        for attempt in range(max_retries):
            try:
                result = await super().call_tool(tool_name, arguments)

                if attempt > 0:
                    print(f"Retry {attempt} succeeded for {tool_name}")

                return result

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Attempt {attempt + 1} failed for {tool_name}: {e}")
                    print(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    print(f"All {max_retries} attempts failed for {tool_name}")
                    raise

# 使用示例
async def main():
    client = ResilientMCPClient(
        ws_url="ws://localhost:8000/mcp/v1",
        jwt_secret="your-secret-key"
    )

    await client.connect()

    try:
        result = await client.call_tool_with_retry(
            "membership.list_members",
            {"page": 1, "limit": 10}
        )
        print("Result:", result)
    finally:
        await client.close()

asyncio.run(main())
```

---

## 错误处理

### 错误码表

| 错误码 | 名称 | 说明 | 处理建议 |
|-------|------|------|---------|
| -32700 | Parse error | JSON解析错误 | 检查消息格式 |
| -32600 | Invalid Request | 无效请求 | 检查请求格式 |
| -32601 | Method not found | 方法不存在 | 检查方法名 |
| -32602 | Invalid params | 参数无效 | 检查参数类型 |
| -32603 | Internal error | 内部错误 | 查看错误详情 |
| -32604 | Error | 通用错误 | 具体错误信息 |

### 错误处理最佳实践

```python
async def safe_tool_call(client: MCPClient, tool_name: str, args: dict):
    """安全的工具调用，包含完整的错误处理"""

    try:
        result = await client.call_tool(tool_name, args)
        return {
            "success": True,
            "data": result
        }

    except Exception as e:
        error_str = str(e)

        # 解析错误码
        if "-32601" in error_str:
            return {
                "success": False,
                "error": "Method not found",
                "suggestion": f"Tool '{tool_name}' not available. Check tools/list for available tools."
            }
        elif "-32603" in error_str:
            return {
                "success": False,
                "error": "Internal server error",
                "suggestion": "Server encountered an error. Please try again later."
            }
        else:
            return {
                "success": False,
                "error": "Unknown error",
                "suggestion": error_str
            }
```

---

## 最佳实践

### 1. 连接管理

✅ **DO**:
- 保持连接长时间活跃，避免频繁重连
- 使用心跳机制检测连接状态
- 优雅地关闭连接

❌ **DON'T**:
- 每个工具调用都创建新连接
- 忽略连接状态检查
- 强制关闭连接而不清理

### 2. Token管理

✅ **DO**:
- 使用环境变量存储JWT密钥
- 设置合理的token过期时间（1小时左右）
- 实现token刷新机制

❌ **DON'T**:
- 硬编码JWT密钥在代码中
- 使用过期的token
- 将token提交到版本控制

### 3. 错误处理

✅ **DO**:
- 捕获并记录所有异常
- 实现重试机制（幂等操作）
- 提供用户友好的错误消息

❌ **DON'T**:
- 忽略错误处理
- 暴露敏感错误信息
- 无限重试

### 4. 性能优化

✅ **DO**:
- 批量调用工具（如果可能）
- 使用异步并发
- 缓存工具列表

❌ **DON'T**:
- 同步阻塞调用
- 重复查询工具列表
- 不必要的轮询

### 5. 安全

✅ **DO**:
- 使用WSS（WebSocket Secure）加密传输
- 验证服务器证书
- 限制token权限范围

❌ **DON'T**:
- 使用WS（非加密）传输敏感数据
- 忽略证书验证
- 使用过度权限的token

---

## 故障排查

### 连接失败

**问题**: 无法连接到WebSocket端点

**检查清单**:
1. 服务是否运行？`curl http://localhost:8000/health`
2. 端口是否正确？`ws://localhost:8000/mcp/v1`
3. Token是否有效？检查JWT过期时间
4. 防火墙是否阻止？检查端口8000

### 认证失败

**问题**: 收到4003关闭码

**检查清单**:
1. Token是否包含mcp权限？
2. JWT密钥是否匹配？
3. Token是否过期？
4. Token格式是否正确（Bearer token）？

### 工具调用失败

**问题**: 收到错误响应

**常见原因**:
- 工具名称错误（使用tools/list查看可用工具）
- 参数格式错误（参考input_schema）
- 权限不足（检查token scopes）
- 后端服务异常

### 性能问题

**问题**: 响应缓慢

**优化建议**:
1. 减少工具列表查询频率
2. 使用异步并发
3. 检查网络延迟
4. 监控服务器负载

---

## 参考资料

- [MCP协议规范](https://modelcontextprotocol.io/)
- [JSON-RPC 2.0规范](https://www.jsonrpc.org/specification)
- [WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [JWT最佳实践](https://jwt.io/introduction)

---

**文档维护**: 本文档应随着API更新同步更新
**问题反馈**: 请在项目issue中提出
