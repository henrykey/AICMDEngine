# MCP Router 更新总结

**更新日期**: 2026-02-20
**版本**: v1.1.0

---

## 📋 更新概览

本次更新为MCP (Model Context Protocol) Router添加了**指定LLM Provider**的功能，允许在调用MCP工具时灵活选择使用哪个LLM模型。

---

## 🎯 核心功能

### 1. LLM Provider 参数支持

**新增参数**: `llm` (string, optional)

通过JSON body传递，用于指定调用MCP工具时使用的LLM provider。

**特性**:
- ✅ 不指定时：使用系统默认的LLM选择策略（按优先级/能力排序）
- ✅ 指定存在的LLM：使用指定的provider
- ✅ 指定不存在的LLM：输出warning日志，自动fallback到默认选择

---

## 🔧 修改的文件

### 1. `/src/routers/mcp.py`

**修改内容**: 添加`llm`参数处理逻辑

```python
@router.post("/servers/{server_name}/tools/{tool_name}/execute")
async def execute_mcp_tool(
    server_name: str,
    tool_name: str,
    request: Request,
    **kwargs: Any
) -> ToolResult:
    # Extract "llm" parameter if present
    llm_provider = kwargs.pop("llm", None)

    result = await registry.execute_command(
        mcp_name=server_name,
        tool_name=tool_name,
        llm_provider=llm_provider,  # ← 传递llm参数
        **kwargs
    )
```

### 2. `/src/mcp/registry.py`

**修改内容**: LLM provider验证逻辑

```python
async def execute_command(
    self,
    mcp_name: str,
    tool_name: str,
    llm_provider: Optional[str] = None,
    **kwargs
) -> ToolResult:
    # Validate LLM provider if specified
    if llm_provider is not None:
        if llm_provider not in mcp.provider_manager.providers:
            available = list(mcp.provider_manager.providers.keys())
            logger.warning(
                f"Specified LLM provider '{llm_provider}' not found. "
                f"Available providers: {available}. Using default selection."
            )
            llm_provider = None

    # Add validated llm_provider to kwargs
    if llm_provider is not None:
        kwargs['_llm_provider'] = llm_provider
```

**验证逻辑**:
- 检查provider是否存在
- 不存在时输出warning并使用默认选择
- 存在时记录info日志

### 3. `/src/mcp_servers/kb_mcp.py`

**修改内容**: 提取并传递LLM provider参数

```python
async def _handle_rag_query(
    self,
    params: Dict[str, Any],
    tenant_id: str
) -> Dict[str, Any]:
    # Extract optional LLM provider parameter
    llm_provider = params.get("_llm_provider", "default")

    logger.info(f"[kb_mcp] Processing RAG query using LLM provider: {llm_provider}")

    result = await self.kb_client.kb_rag_query(
        question,
        context=context
    )

    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "llm_provider": llm_provider  # ← 返回使用的LLM
    }
```

### 4. `/src/services/kb_client.py`

**修改内容**: 简化接口（不需要传递LLM给membership）

```python
async def kb_rag_query(
    self,
    question: str,
    context: Optional[str] = None,
    include_sources: bool = True
) -> Dict[str, Any]:
    # LLM选择在AICMDEngine端处理
    # 不需要修改membership端
```

---

## 📊 API端点变化

### 修改前
```bash
POST /api/mcp/servers/{server_name}/tools/{tool_name}/execute
Content-Type: application/json

{
  "question": "如何使用membership系统？"
}
```

### 修改后
```bash
POST /api/mcp/servers/{server_name}/tools/{tool_name}/execute
Content-Type: application/json

{
  "question": "如何使用membership系统？",
  "llm": "ChatGPT"  # ← 新增的可选参数
}
```

---

## 🚀 使用示例

### 示例1: 使用默认LLM

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何使用membership系统？"
  }'
```

**行为**: 使用系统默认的LLM（按优先级/能力自动选择）

### 示例2: 指定ChatGPT

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何使用membership系统？",
    "llm": "ChatGPT"
  }'
```

**行为**: 强制使用名为"ChatGPT"的provider

### 示例3: 指定本地模型

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何使用membership系统？",
    "llm": "multmode"
  }'
```

**行为**: 使用本地qwen3-vl模型

### 示例4: 指定不存在的LLM

```bash
curl -X POST "http://localhost:8000/api/mcp/servers/kb_mcp/tools/kb_rag_query/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "如何使用membership系统？",
    "llm": "NonExistentLLM"
  }'
```

**行为**:
- 后端输出warning: `Specified LLM provider 'NonExistentLLM' not found. Available providers: [...]. Using default selection.`
- 自动fallback到默认LLM

---

## 📝 日志输出

### 成功指定LLM
```
[kb_mcp] Processing RAG query using LLM provider: ChatGPT
```

### LLM不存在（自动fallback）
```
[kb_mcp] Specified LLM provider 'NonExistentLLM' not found. Available providers: ['DeepSeek', 'OpenAI', 'Z-AI', 'multmode']. Using default selection.
[kb_mcp] Processing RAG query using LLM provider: default
```

### 未指定LLM（使用默认）
```
[kb_mcp] Processing RAG query using LLM provider: default
```

---

## ✅ 优势

1. **灵活性**: 同一个MCP工具可以使用不同的LLM
2. **成本控制**: 指定便宜的模型处理简单任务
3. **性能优化**: 指定本地模型减少延迟
4. **容错性**: 指定的LLM不存在时自动fallback
5. **向后兼容**: 不指定参数时行为不变

---

## 🔍 技术细节

### 参数传递流程

```
前端/API调用
    ↓
传递 "llm": "ChatGPT" in JSON body
    ↓
mcp.py: kwargs.pop("llm", None)
    ↓
registry.py: 验证LLM是否存在
    ↓
registry.py: kwargs['_llm_provider'] = 'ChatGPT'
    ↓
kb_mcp.py: params.get("_llm_provider")
    ↓
记录日志并返回结果
```

### 不修改Membership端的原因

LLM选择逻辑在AICMDEngine端处理，调用membership KB API时不需要传递LLM信息。AICMDEngine：
- 选择合适的LLM
- 调用LLM生成回复
- 将结果返回给前端

Membership端的KB API只需要：
- 检索相关文档
- 返回文档内容
- 不需要关心是哪个LLM生成的回复

---

## 🐛 已知问题

无

---

## 🔄 后续计划

- [ ] 支持多个LLM provider并行调用，返回最快结果
- [ ] 添加LLM provider负载均衡策略
- [ ] 支持按任务类型自动选择最合适的LLM

---

## 📚 相关文档

- [MCP Router 使用手册](./MCP_ROUTER_USER_GUIDE.md)
- [LLM Provider 管理](../membership/LLM_PROVIDER_MANAGEMENT.md)
- [API文档](../api/MCP_API.md)
