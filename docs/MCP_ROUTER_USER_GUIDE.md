# MCP Router 使用手册

**版本**: v1.1.0
**更新日期**: 2026-02-20
**适用系统**: AICMDEngine

---

## 📚 目录

1. [MCP简介](#1-mcp简介)
2. [系统架构](#2-系统架构)
3. [快速开始](#3-快速开始)
4. [API端点说明](#4-api端点说明)
5. [使用示例](#5-使用示例)
6. [高级功能](#6-高级功能)
7. [最佳实践](#7-最佳实践)
8. [故障排除](#8-故障排除)

---

## 1. MCP简介

### 1.1 什么是MCP?

**MCP (Model Context Protocol)** 是一个协议，允许LLM应用通过标准化的方式访问外部工具和数据源。

### 1.2 为什么需要MCP?

传统方式的问题：
- ❌ 每个工具都要写专门的API wrapper
- ❌ 不同工具的接口不统一
- ❌ 难以动态发现和使用新工具

MCP的优势：
- ✅ 统一的接口规范
- ✅ 自动工具发现和注册
- ✅ 标准化的输入输出格式
- ✅ 支持实时工具列表查询

### 1.3 AICMDEngine中的MCP

AICMDEngine实现了一个MCP Registry，用于管理多个MCP服务器：
- **kb_mcp**: 知识库搜索和RAG查询
- **form_mcp**: 表单处理
- **bpmn_mcp**: BPMN工作流操作
- **membership_mcp**: 会员系统操作

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────┐
│         Frontend / Client Application       │
└──────────────────┬──────────────────────────┘
                   │ HTTP/WebSocket
                   ↓
┌─────────────────────────────────────────────┐
│           MCP Router (/api/mcp/*)           │
│  ┌──────────────────────────────────────┐  │
│  │  • List servers                       │  │
│  │  • List tools                         │  │
│  │  • Execute tools (with llm param)   │  │
│  └──────────────────────────────────────┘  │
└──────────────────┬──────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────┐
│           MCP Registry                      │
│  ┌──────────────────────────────────────┐  │
│  │  • Manage MCP servers                │  │
│  │  • Validate LLM providers            │  │
│  │  • Route tool execution             │  │
│  └──────────────────────────────────────┘  │
└──────────────────┬──────────────────────────┘
                   │
        ┌──────────┴──────────┐
        ↓                     ↓
┌──────────────┐      ┌──────────────┐
│  kb_mcp      │      │  form_mcp    │
│  (RAG)       │      │  (Forms)     │
└──────┬───────┘      └──────────────┘
       │
       ↓
┌──────────────┐
│ KB Service   │
│ (Membership) │
└──────────────┘
```

### 2.2 LLM Provider选择

```
┌──────────────────────────────────────┐
│  MCP Tool Execution Request          │
│  {                                  │
│    "question": "...",               │
│    "llm": "ChatGPT"  ← 可选参数     │
│  }                                  │
└──────────┬───────────────────────────┘
           │
           ↓
┌──────────────────────────────────────┐
│  MCP Registry                        │
│  ┌────────────────────────────────┐ │
│  │ 1. 检查llm参数是否存在        │ │
│  │ 2. 如果存在，验证provider     │ │
│  │ 3. 不存在 → warning + fallback │ │
│  │ 4. 存在 → 传递给MCP server     │ │
│  └────────────────────────────────┘ │
└──────────┬───────────────────────────┘
           │
           ↓
┌──────────────────────────────────────┐
│  LLM Provider Manager                │
│  • DeepSeek (默认)                  │
│  • OpenAI                          │
│  • Z-AI                            │
│  • multmode (本地)                 │
└──────────────────────────────────────┘
```

---

## 3. 快速开始

### 3.1 前置条件

确保AICMDEngine服务已启动：
```bash
cd /Users/kehongwei/workspace/AICMDEngine
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3.2 验证MCP服务

检查MCP健康状态：
```bash
curl http://localhost:8000/api/mcp/health
```

预期响应：
```json
{
  "status": "ok",
  "total_servers": 4,
  "servers": ["kb_mcp", "form_mcp", "bpmn_mcp", "membership_mcp"]
}
```

### 3.3 查看可用工具

列出所有MCP工具：
```bash
curl http://localhost:8000/api/mcp/tools
```

---

## 4. API端点说明

### 4.1 健康检查

**端点**: `GET /api/mcp/health`

**描述**: 检查MCP Registry服务状态

**响应**:
```json
{
  "status": "ok",
  "total_servers": 4,
  "servers": ["kb_mcp", "form_mcp", "bpmn_mcp", "membership_mcp"]
}
```

### 4.2 列出MCP服务器

**端点**: `GET /api/mcp/servers`

**描述**: 获取所有注册的MCP服务器列表

**响应**:
```json
{
  "servers": [
    {
      "name": "kb_mcp",
      "status": "running",
      "tools_count": 3,
      "commands_count": 3,
      "health_score": 85
    }
  ]
}
```

### 4.3 获取服务器详情

**端点**: `GET /api/mcp/servers/{server_name}`

**参数**:
- `server_name`: MCP服务器名称（如 kb_mcp）

**响应**:
```json
{
  "name": "kb_mcp",
  "status": "running",
  "tools": {
    "kb_search": {
      "description": "Full-text search against Knowledge Base",
      "input_schema": {...}
    },
    "kb_semantic_search": {...},
    "kb_rag_query": {...}
  }
}
```

### 4.4 列出服务器工具

**端点**: `GET /api/mcp/servers/{server_name}/tools`

**参数**:
- `server_name`: MCP服务器名称

**响应**: 同上，返回工具列表

### 4.5 获取工具详情

**端点**: `GET /api/mcp/servers/{server_name}/tools/{tool_name}`

**参数**:
- `server_name`: MCP服务器名称
- `tool_name`: 工具名称

**响应**:
```json
{
  "name": "kb_rag_query",
  "description": "RAG query with LLM context",
  "input_schema": {
    "type": "object",
    "properties": {
      "question": {"type": "string"},
      "context": {"type": "string"}
    },
    "required": ["question"]
  }
}
```

### 4.6 执行工具（核心端点）

**端点**: `POST /api/mcp/servers/{server_name}/tools/{tool_name}/execute`

**参数**:
- `server_name`: MCP服务器名称
- `tool_name`: 工具名称

**请求体 (JSON)**:
```json
{
  "tool_param1": "value1",
  "tool_param2": "value2",
  "llm": "ChatGPT"  // ← 可选：指定LLM provider
}
```

**响应**:
```json
{
  "success": true,
  "data": {...},
  "llm_provider": "ChatGPT"  // ← 实际使用的LLM
}
```

### 4.7 列出所有工具

**端点**: `GET /api/mcp/tools`

**描述**: 获取所有MCP服务器的所有工具

**响应**:
```json
[
  {
    "server": "kb_mcp",
    "tool": "kb_search",
    "description": "Full-text search...",
    "input_schema": {...}
  },
  {
    "server": "form_mcp",
    "tool": "submit_form",
    ...
  }
]
```

---

## 5. 使用示例

### 5.1 知识库RAG查询

#### 使用默认LLM

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何创建新的会员？"
  }'
```

#### 指定ChatGPT

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何创建新的会员？",
    "llm": "ChatGPT"
  }'
```

#### 指定本地模型（多模态）

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "请描述这个图片的内容",
    "llm": "multmode"
  }'
```

### 5.2 知识库语义搜索

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_semantic_search/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "会员管理功能",
    "similarity_threshold": 0.7,
    "limit": 5
  }'
```

### 5.3 全文搜索

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_search/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "会员权限",
    "limit": 10
  }'
```

### 5.4 表单提交

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/form_mcp/tools/submit_form/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "form_id": "member_registration",
    "form_data": {
      "name": "张三",
      "email": "zhangsan@example.com"
    }
  }'
```

### 5.5 Python调用示例

```python
import requests
import json

BASE_URL = "http://localhost:8000/api/mcp"

def execute_mcp_tool(server_name: str, tool_name: str, params: dict, llm: str = None):
    """执行MCP工具"""
    url = f"{BASE_URL}/servers/{server_name}/tools/{tool_name}/execute"

    # 添加llm参数（如果指定）
    payload = params.copy()
    if llm:
        payload["llm"] = llm

    response = requests.post(url, json=payload)
    response.raise_for_status()

    return response.json()

# 示例1: 使用默认LLM
result = execute_mcp_tool(
    server_name="kb_mcp",
    tool_name="kb_rag_query",
    params={"question": "如何使用membership系统？"}
)
print("Answer:", result["data"]["answer"])

# 示例2: 指定ChatGPT
result = execute_mcp_tool(
    server_name="kb_mcp",
    tool_name="kb_rag_query",
    params={"question": "如何使用membership系统？"},
    llm="ChatGPT"
)
print("Answer:", result["data"]["answer"])
print("LLM Used:", result["data"]["llm_provider"])

# 示例3: 指定本地模型
result = execute_mcp_tool(
    server_name="kb_mcp",
    tool_name="kb_rag_query",
    params={"question": "分析这个图表"},
    llm="multmode"  # 多模态模型
)
print("Answer:", result["data"]["answer"])
```

---

## 6. 高级功能

### 6.1 LLM Provider管理

#### 查看可用Provider

```bash
curl http://localhost:8000/api/llm/providers
```

#### 选择默认Provider

```bash
curl -X GET "http://localhost:8000/api/llm/providers/{provider_name}/select"
```

#### 测试Provider

```bash
curl -X POST "http://localhost:8000/api/llm/providers/{provider_name}/test"
```

### 6.2 错误处理

#### Provider不存在

**请求**:
```json
{
  "question": "...",
  "llm": "NonExistent"
}
```

**日志输出**:
```
[kb_mcp] Specified LLM provider 'NonExistent' not found.
Available providers: ['DeepSeek', 'OpenAI', 'Z-AI', 'multmode'].
Using default selection.
[kb_mcp] Processing RAG query using LLM provider: default
```

**行为**: 自动fallback到默认LLM，不会报错

#### 工具执行失败

**响应**:
```json
{
  "success": false,
  "error": "Tool execution failed: ...",
  "error_code": "TOOL_EXECUTION_ERROR"
}
```

### 6.3 实时工具发现

MCP服务器支持动态工具注册：

```python
# 添加新工具到kb_mcp
async def list_tools(self, tenant_id: str):
    return [
        {
            "name": "kb_hybrid_search",
            "description": "Hybrid search combining full-text and semantic",
            "input_schema": {...}
        }
    ]
```

前端会自动发现新工具，无需重启服务。

---

## 7. 最佳实践

### 7.1 LLM选择策略

#### 按任务类型选择

| 任务类型 | 推荐LLM | 原因 |
|---------|---------|------|
| 简单问答 | DeepSeek | 便宜、快速 |
| 复杂推理 | ChatGPT | 能力强 |
| 多模态（图片）| multmode | 支持vision |
| 代码生成 | ChatGPT | 代码能力强 |

#### 按成本选择

```python
# 简单任务用便宜模型
if task_complexity == "low":
    llm = "DeepSeek"
elif task_complexity == "high":
    llm = "ChatGPT"
else:
    llm = None  # 使用默认
```

### 7.2 性能优化

#### 使用本地模型

```bash
# 本地模型无网络延迟，适合实时应用
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "实时查询",
    "llm": "multmode"
  }'
```

#### 批量处理

```python
# 批量查询时使用不同LLM并行
from concurrent.futures import ThreadPoolExecutor

questions = ["问题1", "问题2", "问题3"]

with ThreadPoolExecutor(max_workers=3) as executor:
    futures = []
    for q in questions:
        future = executor.submit(
            execute_mcp_tool,
            "kb_mcp",
            "kb_rag_query",
            {"question": q},
            "DeepSeek"  # 使用便宜模型
        )
        futures.append(future)

    results = [f.result() for f in futures]
```

### 7.3 错误处理

```python
def safe_mcp_call(server_name: str, tool_name: str, params: dict, llm: str = None):
    try:
        result = execute_mcp_tool(server_name, tool_name, params, llm)

        if not result.get("success"):
            # 记录错误
            logger.error(f"MCP tool failed: {result.get('error')}")
            return None

        return result["data"]

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return None
```

### 7.4 日志监控

启用详细日志：
```python
import logging

logging.basicConfig(level=logging.INFO)
# 或在uvicorn启动时：--log-level info
```

关键日志：
- `[kb_mcp] Processing RAG query using LLM provider: {provider_name}`
- `Specified LLM provider '{name}' not found. Available: [...]`
- `Tool execution failed: {error}`

---

## 8. 故障排除

### 8.1 MCP服务未启动

**症状**: `curl: (7) Failed to connect to localhost port 8000`

**解决方案**:
```bash
# 检查服务状态
ps aux | grep uvicorn

# 重启服务
cd /Users/kehongwei/workspace/AICMDEngine
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 8.2 MCP Registry未初始化

**症状**: 响应 `{"detail": "MCP Registry not initialized"}`

**解决方案**: 检查`src/main.py`中MCP registry初始化代码

### 8.3 Tool执行超时

**症状**: 长时间等待后超时

**解决方案**:
- 检查LLM provider是否可用
- 增加超时时间
- 使用更快的LLM provider

### 8.4 LLM Provider不存在

**症状**: Warning日志 `Specified LLM provider 'X' not found`

**解决方案**:
```bash
# 查看可用providers
curl http://localhost:8000/api/llm/providers

# 使用正确的provider名称
# 或不指定llm参数，使用默认选择
```

### 8.5 返回结果不正确

**检查清单**:
1. ✅ 工具名称是否正确
2. ✅ 参数格式是否符合input_schema
3. ✅ 必填参数是否都提供了
4. ✅ LLM provider是否可用

**调试方法**:
```python
# 查看工具详情
curl http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query

# 对比input_schema和你的参数
```

---

## 9. 附录

### 9.1 状态码

| 状态码 | 说明 |
|-------|------|
| 200 | 成功 |
| 404 | MCP服务器或工具不存在 |
| 500 | 服务器内部错误 |
| 503 | MCP Registry未初始化 |

### 9.2 错误码

| 错误码 | 说明 |
|-------|------|
| MCP_NOT_FOUND | MCP服务器不存在 |
| TOOL_NOT_FOUND | 工具不存在 |
| TOOL_EXECUTION_ERROR | 工具执行失败 |

### 9.3 相关链接

- [MCP Protocol规范](https://modelcontextprotocol.io/)
- [LLM Provider管理](../membership/LLM_PROVIDER_MANAGEMENT.md)
- [更新日志](./MCP_ROUTER_UPDATE_SUMMARY.md)

---

**文档维护**: AICMDEngine开发团队
**最后更新**: 2026-02-20
**文档版本**: v1.0
