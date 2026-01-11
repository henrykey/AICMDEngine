# MCP API Reference

This document provides detailed API reference for the MCP (Model Context Protocol) framework in AICMDEngine.

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Server Management APIs](#server-management-apis)
4. [Tool Execution APIs](#tool-execution-apis)
5. [Health Check APIs](#health-check-apis)
6. [Error Handling](#error-handling)
7. [Response Formats](#response-formats)
8. [SDKs and Examples](#sdks-and-examples)

## Overview

The MCP framework provides RESTful APIs for managing MCP servers and executing tools. All endpoints are prefixed with `/v1/mcp/`.

### Base URL

```
http://localhost:8000/v1/mcp
```

### Content Types

- **Request**: `application/json`
- **Response**: `application/json`

### Common Response Structure

```json
{
  "success": true,
  "content": "Success message",
  "metadata": {},
  "error_code": null,
  "error_message": null
}
```

## Authentication

Currently, the MCP framework does not require authentication for development. For production deployment, consider implementing authentication:

```python
# Example: API Key authentication
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != "your-secret-api-key":
        raise HTTPException(
            status_code=403,
            detail="Invalid API Key"
        )
    return api_key
```

## Server Management APIs

### List All Servers

**Endpoint:** `GET /v1/mcp/servers`

**Description:** Retrieve a list of all registered MCP servers with their status and metadata.

**Parameters:** None

**Response:**
```json
{
  "servers": [
    {
      "_id": "1234567890",
      "name": "membership",
      "type": "builtin",
      "endpoint": "mcp://membership",
      "status": "running",
      "health_score": 85,
      "last_heartbeat": "2024-01-09T19:30:00.000Z",
      "tools_count": 7,
      "commands_count": 7,
      "metadata": {
        "description": "Membership management MCP server",
        "version": "1.0.0",
        "author": "AICMDEngine Team",
        "dependencies": []
      }
    },
    {
      "_id": "0987654321",
      "name": "your-server",
      "type": "custom",
      "endpoint": "mcp://your-server",
      "status": "stopped",
      "health_score": 40,
      "last_heartbeat": "2024-01-09T19:25:00.000Z",
      "tools_count": 3,
      "commands_count": 3,
      "metadata": {
        "description": "Your custom MCP server",
        "version": "1.0.0",
        "author": "Your Name",
        "dependencies": []
      }
    }
  ]
}
```

**Example:**
```bash
curl -X GET "http://localhost:8000/v1/mcp/servers" | jq
```

### Get Server Details

**Endpoint:** `GET /v1/mcp/servers/{server_name}`

**Description:** Get detailed information about a specific MCP server.

**Parameters:**
- `server_name` (path, required): Name of the server

**Response:**
```json
{
  "name": "membership",
  "version": "1.0.0",
  "description": "Membership management MCP server",
  "author": "AICMDEngine Team",
  "status": "running",
  "is_initialized": true,
  "last_heartbeat": "2024-01-09T19:30:00.000Z",
  "tools": {
    "create_membership": {
      "name": "create_membership",
      "description": "Create a new membership",
      "input_schema": {
        "type": "object",
        "properties": {
          "email": {"type": "string", "format": "email"},
          "plan": {"type": "string", "enum": ["basic", "premium", "enterprise"]}
        },
        "required": ["email"]
      },
      "status": "active"
    },
    "get_member_profile": {
      "name": "get_member_profile",
      "description": "Retrieve member profile",
      "input_schema": {
        "type": "object",
        "properties": {
          "member_id": {"type": "string"}
        },
        "required": ["member_id"]
      },
      "status": "active"
    }
  },
  "metadata": {
    "dependencies": [],
    "server_type": "builtin",
    "endpoint": "mcp://membership"
  }
}
```

**Example:**
```bash
curl -X GET "http://localhost:8000/v1/mcp/servers/membership" | jq
```

### List Server Tools

**Endpoint:** `GET /v1/mcp/servers/{server_name}/tools`

**Description:** Get all tools available in a specific server.

**Parameters:**
- `server_name` (path, required): Name of the server

**Response:** Same as `Get Server Details` but focused on tools.

**Example:**
```bash
curl -X GET "http://localhost:8000/v1/mcp/servers/membership/tools" | jq
```

### Get Tool Details

**Endpoint:** `GET /v1/mcp/servers/{server_name}/tools/{tool_name}`

**Description:** Get detailed information about a specific tool in a server.

**Parameters:**
- `server_name` (path, required): Name of the server
- `tool_name` (path, required): Name of the tool

**Response:**
```json
{
  "name": "create_membership",
  "description": "Create a new membership",
  "input_schema": {
    "type": "object",
    "properties": {
      "email": {
        "type": "string",
        "description": "Member email address",
        "format": "email"
      },
      "plan": {
        "type": "string",
        "description": "Membership plan",
        "enum": ["basic", "premium", "enterprise"],
        "default": "basic"
      },
      "metadata": {
        "type": "object",
        "description": "Additional metadata",
        "properties": {
          "referral_code": {"type": "string"},
          "source": {"type": "string"}
        }
      }
    },
    "required": ["email"],
    "additionalProperties": false
  },
  "status": "active",
  "example_usage": {
    "email": "user@example.com",
    "plan": "premium",
    "metadata": {
      "referral_code": "ABC123",
      "source": "web"
    }
  }
}
```

**Example:**
```bash
curl -X GET "http://localhost:8000/v1/mcp/servers/membership/tools/create_membership" | jq
```

### Refresh Server Status

**Endpoint:** `POST /v1/mcp/servers/{server_name}/refresh`

**Description:** Refresh the status of a specific MCP server.

**Parameters:**
- `server_name` (path, required): Name of the server

**Request Body:** None

**Response:**
```json
{
  "success": true,
  "message": "Server 'membership' status refreshed",
  "status": "running"
}
```

**Example:**
```bash
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/refresh" | jq
```

### Start Server

**Endpoint:** `POST /v1/mcp/servers/{server_name}/start`

**Description:** Start an MCP server.

**Parameters:**
- `server_name` (path, required): Name of the server

**Request Body:** None

**Response:**
```json
{
  "success": true,
  "message": "Server 'membership' started successfully",
  "status": "running"
}
```

**Example:**
```bash
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/start" | jq
```

### Stop Server

**Endpoint:** `POST /v1/mcp/servers/{server_name}/stop`

**Description:** Stop an MCP server.

**Parameters:**
- `server_name` (path, required): Name of the server

**Request Body:** None

**Response:**
```json
{
  "success": true,
  "message": "Server 'membership' stopped successfully",
  "status": "stopped"
}
```

**Example:**
```bash
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/stop" | jq
```

### Delete Server

**Endpoint:** `DELETE /v1/mcp/servers/{server_name}`

**Description:** Delete an MCP server from the registry.

**Parameters:**
- `server_name` (path, required): Name of the server

**Request Body:** None

**Response:**
```json
{
  "success": true,
  "message": "Server 'membership' deleted successfully"
}
```

**Example:**
```bash
curl -X DELETE "http://localhost:8000/v1/mcp/servers/membership" | jq
```

## Tool Execution APIs

### Execute Tool

**Endpoint:** `POST /v1/mcp/servers/{server_name}/tools/{tool_name}`

**Description:** Execute a tool from a specific MCP server.

**Parameters:**
- `server_name` (path, required): Name of the server
- `tool_name` (path, required): Name of the tool

**Request Body:** Tool-specific parameters based on the tool's schema.

**Response:**
```json
{
  "success": true,
  "content": "Membership created successfully",
  "metadata": {
    "membership_id": "12345",
    "email": "user@example.com",
    "plan": "premium",
    "created_at": "2024-01-09T19:30:00.000Z",
    "status": "active"
  },
  "error_code": null,
  "error_message": null
}
```

**Examples:**

**Example 1: Create Membership**
```bash
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/tools/create_membership" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "plan": "premium",
    "metadata": {
      "referral_code": "ABC123",
      "source": "web"
    }
  }' | jq
```

**Example 2: Get Member Profile**
```bash
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/tools/get_member_profile" \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": "12345"
  }' | jq
```

### List All Tools

**Endpoint:** `GET /v1/mcp/tools`

**Description:** List all tools from all registered MCP servers.

**Parameters:** None

**Response:**
```json
[
  {
    "server": "membership",
    "tool": "create_membership",
    "name": "create_membership",
    "description": "Create a new membership",
    "input_schema": {
      "type": "object",
      "properties": {
        "email": {"type": "string", "format": "email"}
      },
      "required": ["email"]
    },
    "status": "active"
  },
  {
    "server": "membership",
    "tool": "get_member_profile",
    "name": "get_member_profile",
    "description": "Retrieve member profile",
    "input_schema": {
      "type": "object",
      "properties": {
        "member_id": {"type": "string"}
      },
      "required": ["member_id"]
    },
    "status": "active"
  },
  {
    "server": "your-server",
    "tool": "greet",
    "name": "greet",
    "description": "Generate a greeting message",
    "input_schema": {
      "type": "object",
      "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 100},
        "enthusiasm": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}
      },
      "required": ["name"]
    },
    "status": "active"
  }
]
```

**Example:**
```bash
curl -X GET "http://localhost:8000/v1/mcp/tools" | jq
```

## Health Check APIs

### MCP Registry Health

**Endpoint:** `GET /v1/mcp/health`

**Description:** Health check for the MCP Registry.

**Parameters:** None

**Response:**
```json
{
  "status": "ok",
  "total_servers": 2,
  "servers": ["membership", "your-server"]
}
```

**Example:**
```bash
curl -X GET "http://localhost:8000/v1/mcp/health" | jq
```

## Error Handling

### Error Response Format

All error responses follow this format:

```json
{
  "success": false,
  "content": null,
  "metadata": null,
  "error_code": "ERROR_CODE",
  "error_message": "Human-readable error message"
}
```

### Common Error Codes

| Error Code | HTTP Status | Description |
|------------|-------------|-------------|
| `MCP_NOT_FOUND` | 404 | MCP server not found in registry |
| `TOOL_NOT_FOUND` | 404 | Tool not found in specified server |
| `INVALID_PARAMETERS` | 400 | Invalid tool parameters |
| `TIMEOUT_ERROR` | 504 | Tool execution timeout |
| `AUTH_ERROR` | 401 | Authentication failed |
| `API_ERROR` | 500 | External API error |
| `INTERNAL_ERROR` | 500 | Internal server error |

### Example Error Response

```json
{
  "success": false,
  "content": null,
  "metadata": null,
  "error_code": "INVALID_PARAMETERS",
  "error_message": "Missing required parameter: email"
}
```

## Response Formats

### ToolResult Response

```json
{
  "success": true,
  "content": "Success message or data",
  "metadata": {
    "additional_data": "value"
  },
  "error_code": null,
  "error_message": null
}
```

#### Fields Description

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether the operation succeeded |
| `content` | string | Success message or data |
| `metadata` | object | Additional data (can be null) |
| `error_code` | string | Error code (null on success) |
| `error_message` | string | Human-readable error message |

## SDKs and Examples

### Python SDK

```python
import asyncio
import aiohttp
from typing import Dict, Any

class MCPClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url

    async def list_servers(self) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/v1/mcp/servers") as response:
                return await response.json()

    async def execute_tool(
        self,
        server_name: str,
        tool_name: str,
        **kwargs
    ) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/v1/mcp/servers/{server_name}/tools/{tool_name}"
            async with session.post(url, json=kwargs) as response:
                return await response.json()

# Usage example
async def main():
    client = MCPClient()

    # List servers
    servers = await client.list_servers()
    print("Available servers:", servers)

    # Execute tool
    result = await client.execute_tool(
        "membership",
        "create_membership",
        email="user@example.com",
        plan="premium"
    )
    print("Tool result:", result)

asyncio.run(main())
```

### JavaScript/Node.js SDK

```javascript
const axios = require('axios');

class MCPClient {
    constructor(baseUrl = 'http://localhost:8000') {
        this.baseUrl = baseUrl;
        this.client = axios.create({
            baseURL: this.baseUrl,
            headers: {
                'Content-Type': 'application/json'
            }
        });
    }

    async listServers() {
        const response = await this.client.get('/v1/mcp/servers');
        return response.data;
    }

    async executeTool(serverName, toolName, params = {}) {
        const response = await this.client.post(
            `/v1/mcp/servers/${serverName}/tools/${toolName}`,
            params
        );
        return response.data;
    }
}

// Usage example
async function main() {
    const client = new MCPClient();

    try {
        // List servers
        const servers = await client.listServers();
        console.log('Available servers:', servers);

        // Execute tool
        const result = await client.executeTool(
            'membership',
            'create_membership',
            {
                email: 'user@example.com',
                plan: 'premium'
            }
        );
        console.log('Tool result:', result);
    } catch (error) {
        console.error('Error:', error.response?.data || error.message);
    }
}

main();
```

### cURL Examples

#### Basic Operations
```bash
# List all servers
curl -X GET "http://localhost:8000/v1/mcp/servers"

# Get server details
curl -X GET "http://localhost:8000/v1/mcp/servers/membership"

# List all tools
curl -X GET "http://localhost:8000/v1/mcp/tools"
```

#### Tool Execution
```bash
# Execute with valid parameters
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/tools/create_membership" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "plan": "premium"
  }'

# Execute with missing required parameter
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/tools/create_membership" \
  -H "Content-Type: application/json" \
  -d '{"plan": "premium"}'

# Execute with invalid parameter
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/tools/create_membership" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "invalid-email",
    "plan": "invalid-plan"
  }'
```

#### Server Management
```bash
# Refresh server status
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/refresh"

# Start server
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/start"

# Stop server
curl -X POST "http://localhost:8000/v1/mcp/servers/membership/stop"

# Delete server
curl -X DELETE "http://localhost:8000/v1/mcp/servers/membership"
```

### WebSocket Support (Future Enhancement)

For real-time updates, WebSocket support can be added:

```javascript
// WebSocket client example
const ws = new WebSocket('ws://localhost:8000/v1/mcp/ws');

ws.onopen = () => {
    console.log('Connected to MCP WebSocket');
    ws.send(JSON.stringify({
        type: 'subscribe',
        server: 'membership'
    }));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Server update:', data);
};
```

This API reference provides comprehensive documentation for integrating with the MCP framework through REST APIs. The endpoints cover server management, tool execution, health monitoring, and error handling to support robust application development.