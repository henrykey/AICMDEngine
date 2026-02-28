# MCP 服务器生态目录

本目录统一管理所有 MCP (Model Context Protocol) 服务器。

## 目录结构

```
mcp/
├── servers/              # MCP 服务器实现
│   ├── paddleocr/       # PaddleOCR MCP (OCR 识别)
│   └── office-word/     # Office Word MCP (Word 文档操作)
│
├── proxy/               # HTTP/SSE 代理服务（Legacy SSE 协议）
│   ├── src/             # 代理源码
│   ├── config/          # 配置文件
│   └── requirements.txt # 依赖
│
└── start-proxy.sh      # 启动脚本
```

## 快速开始

### 1. 启动 HTTP/SSE 代理（将 stdio MCP 转换为 HTTP/SSE）

```bash
cd /Users/kehongwei/workspace/AICMDEngine/mcp
./start-proxy.sh
```

这会启动以下 HTTP/SSE 服务：
- **PaddleOCR**: `http://localhost:9001`（`GET /sse` + `POST /messages`）
- **Office Word**: `http://localhost:9002`（`GET /sse` + `POST /messages`）

### 2. 配置 MCP Router 连接

在 `docker-compose.dev.yml` 中配置：

```yaml
mcp-router:
  environment:
    EXTERNAL_MCPS: '{"paddleocr":{"transport":"http","url":"http://host.docker.internal:9001"},"office-word":{"transport":"http","url":"http://host.docker.internal:9002"}}'
```

## 架构

```
┌─────────────────────────────────────────────────────┐
│ Host Machine                                          │
│                                                       │
│  ┌─────────────────────────────────────────────┐    │
│  │ MCP HTTP/SSE Proxy (本代理)                   │    │
│  │ - 端口 9001: PaddleOCR MCP                   │    │
│  │ - 端口 9002: Office Word MCP                 │    │
│  └────────────┬────────────────────────────────┘    │
│               │                                     │
│      通过 stdio 启动各 MCP:                        │
│      python -m paddleocr_mcp                          │
│      python word_mcp_server.py                    │
│                                                       │
└───────────────┬───────────────────────────────────┘
                │ HTTP/SSE (Legacy SSE)
┌───────────────▼───────────────────────────────────┐
│ Docker Network                                      │
│  ┌──────────────────┐                              │
│  │ MCP Router 容器   │                              │
│  │ http://host.      │                              │
│  │ docker.internal  │                              │
│  └──────────────────┘                              │
└────────────────────────────────────────────────────┘
```

## 可用 MCP 服务器

### PaddleOCR MCP
- **功能**: OCR 文字识别
- **端口**: 9001
- **项目**: https://github.com/PaddlePaddle/PaddleOCR
- **使用**: 图片 OCR、文档识别

### Office Word MCP
- **功能**: Microsoft Word 文档操作
- **端口**: 9002
- **项目**: https://github.com/GongRzhe/Office-Word-MCP-Server
- **使用**: 创建、编辑 Word 文档

### PDF Extraction MCP
- **功能**: PDF 内容提取
- **端口**: 9003
- **项目**: https://github.com/lh/mcp-pdf-extraction-server
- **使用**: PDF 文本提取

## 配置

编辑 `proxy/config/mcp-proxy-config.yml` 来添加或修改 MCP 服务器：

```yaml
servers:
  - name: your-mcp
    port: 9004
    cwd: ../servers/your-mcp
    command: ["python"]
    args: ["-m", "your_mcp_module"]
    env:
      KEY: "value"
```

## 优势

- ✅ **统一管理**: 所有 MCP 集中在一个目录
- ✅ **网络解耦**: MCP Router 通过 HTTP/SSE 连接，无需在容器内安装依赖
- ✅ **独立部署**: 每个 MCP 可以独立启动、停止、升级
- ✅ **语言无关**: 支持 Python、Node.js 等任何语言的 stdio MCP
- ✅ **配置驱动**: 只需修改 YAML 配置文件即可添加新 MCP

## 开发

### 添加新的 MCP 服务器

1. Clone MCP 仓库到 `mcp/servers/`
2. 在 `mcp/proxy/config/mcp-proxy-config.yml` 添加配置
3. 重启代理服务

### 代理开发

代理源码在 `mcp/proxy/src/mcp_proxy.py`，实现了：
- stdio 进程管理
- HTTP/SSE (Legacy SSE) <-> stdio 消息转发
- JSON-RPC 协议透传
- 多 MCP 并发处理

## 故障排查

### 检查代理状态

```bash
# 查看代理日志
cd mcp
./start-proxy.sh

# 检查端口占用
lsof -i :9001
lsof -i :9002
lsof -i :9003
```

### 测试 HTTP/SSE 连接

```bash
# 测试 SSE 端点（应返回 event: endpoint）
curl -N http://localhost:9001/sse

# 或用 curl 快速验证代理存活
curl -s -o /dev/null -w "%{http_code}" http://localhost:9001/sse --max-time 2
```

## 相关链接

- [MCP Protocol 规范](https://modelcontextprotocol.io/)
- [MCP Router](../src/mcp/): 路由服务
- [AICMDEngine 文档](../docs/)
