# Release Notes — v1.01

**Release Date:** 2026-02-28

---

## Summary

本版本聚焦于 MCP 外部服务接入层的完整重构，实现了 stdio MCP 进程的 HTTP 代理化，并完成 PaddleOCR 与 Office Word 两个外部 MCP 的集成验证。

---

## New Features

### MCP Proxy — stdio-to-HTTP 桥接代理
- 新增 `mcp/proxy` 本地代理服务，将任意 stdio MCP 进程桥接为 HTTP/SSE 服务
- 支持 **Streamable-HTTP**（`POST /mcp`）与 **Legacy SSE**（`GET /sse` + `POST /messages`）双协议
- 启动时自动执行 `initialize` + `notifications/initialized` 握手，解决 stdio MCP 进程拒绝请求（-32602）的问题
- 支持通过 `mcp-proxy-config.yml` 同时管理多个 stdio MCP 进程，各自独立端口

### Office Word MCP 集成
- 将 Office Word MCP（`mcp/servers/office-word`）接入代理，监听端口 `9002`
- Router 通过 `EXTERNAL_MCPS` 自动发现并注册全部 **54 个 Word 操作工具**
- 与 PaddleOCR MCP 并行运行，零冲突

### MCP Router — 外部 MCP 协议自动检测
- `external_mcp.py` 新增协议探测逻辑：优先尝试 Streamable-HTTP（`/mcp`），失败则降级到 Legacy SSE（`/sse`）
- 引入 `sse_mode` 标志，`_execute_tool_http()` 和 `_discover_tools_http()` 均按实际协议分支处理
- 连接、工具发现、工具调用全链路经过测试验证

---

## Bug Fixes

- **路由器连接代理 404**：代理缺少 `/mcp` 端点，Router 的 streamable-http 请求返回 404 → 已添加 `POST /mcp` 端点
- **全部请求返回 -32602**：stdio 进程未完成握手即收到 `tools/list`/`tools/call` 请求 → 代理启动时强制完成握手
- **PaddleOCR Docker 容器相对导入错误**：Dockerfile CMD 由 `python /app/server.py` 改为 `python -m paddleocr_mcp`
- **plan2-ui Docker 构建上下文错误**：`docker-compose.mcp-servers.yml` 中 build context 由 `./ui/dist` 更正为 `./plan2`

---

## Infrastructure / Config Changes

| 文件 | 变更内容 |
|---|---|
| `mcp/proxy/src/mcp_proxy.py` | 新增 `_stdio_handshake()`、`POST /mcp` 端点、`mcp_pending` 异步 future 机制 |
| `mcp/proxy/config/mcp-proxy-config.yml` | 新增 `office-word` 服务项（端口 9002） |
| `src/mcp/external_mcp.py` | 协议自动检测、sse_mode 分支、连接日志优化 |
| `docker-compose.mcp-servers.yml` | `EXTERNAL_MCPS` 增加 `office-word`；Docker 容器版端口改为 9003 避免与代理冲突；修正 `plan2-ui` build context |
| `mcp/servers/paddleocr/Dockerfile` | CMD 修正为 `python -m paddleocr_mcp --http` |

---

## Verified

| 场景 | 结果 |
|---|---|
| Router → Proxy → paddleocr stdio → OCR | ✅ |
| Router → Proxy → office-word stdio → 工具列表（54 tools） | ✅ |
| Legacy SSE 降级连接 | ✅ |
| 代理多进程并发启动 | ✅ |
