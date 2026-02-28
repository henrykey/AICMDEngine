# MCP 容器化部署架构

## 🎯 项目概述

本项目实现了 **MCP (Model Context Protocol) 服务器的容器化部署架构**，通过统一的 MCP Proxy 管理多个 MCP 服务器，并支持开发环境（进程模式）和生产环境（容器模式）两种部署方式。

## 📁 项目结构

```
AICMDEngine/
├── mcp/
│   ├── proxy/                    # MCP Proxy (核心管理层)
│   │   ├── src/
│   │   │   └── mcp_proxy.py     # Proxy 主程序（支持 process/docker 双模式）
│   │   └── config/
│   │       └── mcp-proxy-config.yml  # 配置文件
│   └── servers/                  # MCP 服务器实现
│       ├── paddleocr/           # PaddleOCR MCP
│       │   └── Dockerfile
│       └── office-word/         # Office Word MCP
│           └── Dockerfile
├── docker-compose.mcp-servers.yml  # MCP 容器编排配置
├── scripts/                      # 运维脚本
│   ├── start-mcp-proxy.sh       # 启动脚本
│   └── stop-mcp-services.sh     # 停止脚本
└── docs/
    └── MCP_CONTAINER_DEPLOYMENT.md  # 详细部署文档
```

## 🏗️ 架构设计

### 核心组件

1. **MCP Proxy** (`mcp/proxy/`)
   - 职责：统一管理所有 MCP 服务器
   - 功能：stdio → HTTP/SSE 转换（Legacy SSE 协议）、端口分配、生命周期管理
   - 运行位置：Host 机器（需要 Docker 权限）

2. **MCP Servers** (`mcp/servers/`)
   - PaddleOCR MCP：OCR 文字识别服务
   - Office Word MCP：Word 文档操作服务
   - 部署方式：本地进程或 Docker 容器

3. **MCP Router** (独立服务)
   - 职责：提供统一的 API 接口
   - 连接方式：通过 HTTP/SSE 连接 MCP Proxy（`transport: http`）

### 部署模式对比

| 特性 | 进程模式（开发） | 容器模式（生产） |
|------|----------------|----------------|
| **启动方式** | MCP Proxy 启动本地进程 | MCP Proxy 连接 Docker 容器 |
| **隔离性** | 共享 Host 环境 | 容器级别隔离 |
| **资源管理** | 无法限制 | CPU/内存限制 |
| **调试难度** | 简单（直接查看日志） | 中等（需要 docker logs） |
| **部署复杂度** | 低 | 中等 |
| **适用场景** | 开发、测试 | 生产环境 |

## 🚀 快速开始

### 前置要求

- Python 3.11+
- Docker & Docker Compose
- Make（可选）

### 开发环境（进程模式）

```bash
# 1. 启动 MCP Proxy
./scripts/start-mcp-proxy.sh

# MCP Proxy 会自动启动:
# - paddleocr (http://localhost:9001)
# - office-word (http://localhost:9002)
```

### 生产环境（容器模式）

```bash
# 1. 启动 MCP 容器
docker-compose -f docker-compose.mcp-servers.yml up -d

# 2. 切换配置到容器模式
# 编辑 mcp/proxy/config/mcp-proxy-config.yml
# 将 type: process 改为 type: docker

# 3. 启动 MCP Proxy
./scripts/start-mcp-proxy.sh
```

### 停止服务

```bash
# 停止所有 MCP 服务（容器和进程）
./scripts/stop-mcp-services.sh
```

## ⚙️ 配置说明

### MCP Proxy 配置文件

**位置**: `mcp/proxy/config/mcp-proxy-config.yml`

**示例配置**:

```yaml
# 方式 1: 进程模式（开发环境）
servers:
  - name: paddleocr
    type: process      # 启动本地进程
    port: 9001
    cwd: ../../servers/paddleocr
    command: ["python"]
    args: ["-m", "paddleocr_mcp"]
    env:
      PADDLEOCR_MCP_PIPELINE: "OCR"

  - name: office-word
    type: process      # 启动本地进程
    port: 9002
    cwd: ../../servers/office-word
    command: ["python"]
    args: ["word_mcp_server.py"]

# 方式 2: 容器模式（生产环境）
# servers:
#   - name: paddleocr
#     type: docker       # 连接到 Docker 容器
#     port: 9001
#     container: paddleocr-mcp
#
#   - name: office-word
#     type: docker
#     port: 9002
#     container: office-word-mcp
```

### MCP Router 配置

**位置**: membership 项目 `docker-compose.dev.yml`

```yaml
mcp-router:
  environment:
    EXTERNAL_MCPS: '{"paddleocr":{"transport":"http","url":"http://host.docker.internal:9001"},"office-word":{"transport":"http","url":"http://host.docker.internal:9002"}}'
```

## 📊 完整架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              MCP Proxy (Port 9003)                      │   │
│  │              /mcp/proxy/src/mcp_proxy.py                │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │  Mode Switcher                                  │   │   │
│  │  │  - type: process → 启动本地进程                  │   │   │
│  │  │  - type: docker  → 连接 Docker 容器              │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  │                                                          │   │
│  │  Port 9001 ◄─────────┐  Port 9002 ◄─────────┐          │   │
│  │     (HTTP/SSE)        │     (HTTP/SSE)        │          │   │
│  │                       │                     │   │            │   │
│  └───────────────────────┼─────────────────────┼───────────┘   │
│                        │                     │                  │
│         ┌───────────────┴─┐         ┌───────┴────────────┐     │
│         │  Process Mode  │         │  Docker Mode       │     │
│         │  (开发环境)     │         │  (生产环境)        │     │
│         │                │         │                    │     │
│         │  Local:        │         │  Container:        │     │
│         │  - paddleocr   │         │  - paddleocr-mcp   │     │
│         │  - office-word │         │  - office-word-mcp │     │
│         └────────────────┘         └────────────────────┘     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ host.docker.internal
                            │ HTTP/SSE (9001/9002)
                            │
┌───────────────────────────▼──────────────────────────────────┐
│                  Docker Network (membership)                │
│                                                              │
│  ┌───────────────────────────────────────────────────┐     │
│  │       MCP Router (FastAPI)                         │     │
│  │       Port: 8000                                    │     │
│  │                                                     │     │
│  │  EXTERNAL_MCPS:                                     │     │
  │  - http://host.docker.internal:9001 (paddleocr)   │     │
  │  - http://host.docker.internal:9002 (office-word) │     │
│  └───────────────────────────────────────────────────┘     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## 🛠️ 开发指南

### 添加新的 MCP Server

#### 1. 创建 MCP Server Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app

# 安装依赖
RUN pip install your-mcp-package

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "your_mcp"]
```

#### 2. 添加到 docker-compose.mcp-servers.yml

```yaml
services:
  your-mcp:
    build: ./mcp/servers/your-mcp
    image: your-mcp:latest
    container_name: your-mcp
    restart: unless-stopped
    resources:
      limits:
        cpus: '1'
        memory: 512M
```

#### 3. 更新 mcp-proxy-config.yml

```yaml
servers:
  - name: your-mcp
    type: docker  # 或 process
    port: 9003
    container: your-mcp  # 如果是 docker 模式
    # cwd, command, args  # 如果是 process 模式
```

#### 4. 更新 MCP Router 配置

```yaml
EXTERNAL_MCPS: >
  {
    "paddleocr": {...},
    "office-word": {...},
    "your-mcp": {
      "transport": "http",
      "url": "http://host.docker.internal:9003"
    }
  }
```

## 🐛 故障排查

### 问题 1: 容器无法启动

```bash
# 查看容器日志
docker logs paddleocr-mcp
docker logs office-word-mcp

# 检查容器状态
docker ps -a
```

### 问题 2: MCP Proxy 无法连接容器

```bash
# 检查容器是否运行
docker ps | grep paddleocr

# 测试 docker exec
docker exec -it paddleocr-mcp python -c "print('test')"

# 检查 MCP Proxy 配置
cat mcp/proxy/config/mcp-proxy-config.yml | grep type
```

### 问题 3: HTTP/SSE 连接失败

```bash
# 检查端口占用
lsof -i :9001
lsof -i :9002

# 测试 SSE 端点是否正常
curl -N http://localhost:9001/sse

# 检查 MCP Proxy 日志
# 日志会显示详细的连接信息
```

## 📚 相关文档

- [详细部署文档](docs/MCP_CONTAINER_DEPLOYMENT.md)
- [MCP 协议规范](https://modelcontextprotocol.io/)
- [PaddleOCR MCP 文档](https://github.com/GuDaDa/paddleocr-mcp)
- [Office Word MCP 文档](https://github.com/smithberkeley/MCP-Server-Office-Word)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

本项目采用 Apache 2.0 许可证。

---

**最后更新**: 2026-02-28
**版本**: v1.0.0
