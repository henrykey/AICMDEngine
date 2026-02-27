# MCP 容器化部署架构文档

## 📋 架构总结

### 核心设计
```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              MCP Proxy (Host 运行)                       │   │
│  │              Port: 9003 (管理端口)                      │   │
│  │                                                          │   │
│  │  职责:                                                   │   │
│  │  1. 管理 Docker 容器中的 MCP servers                     │   │
│  │  2. 容器生命周期管理（启动/停止/重启）                    │   │
│  │  3. stdio → WebSocket 转换                               │   │
│  │  4. 分配 WebSocket 端口: 9001, 9002, ...                │   │
│  └────────┬─────────────────────────────────────────────┘   │
│           │                                                     │
│           │ docker exec (stdio 通信)                          │
│           │                                                     │
│  ┌────────┴────────────────┐  ┌──────────────────┐            │
│  │   Docker Container     │  │ Docker Container  │            │
│  │   ┌────────────────┐   │  │ ┌──────────────┐ │            │
│  │   │ PaddleOCR MCP  │   │  │ │Office-Word MCP│ │            │
│  │   │ (stdio protocol)│   │  │ │(stdio protocol)│ │            │
│  │   └────────┬───────┘   │  │ └──────┬───────┘ │            │
│  │            │stdio       │  │        │stdio     │            │
│  │   Port:9001│◄──────────┘  │ Port:9002│◄─────────┘            │
│  │   (WebSocket)            │ (WebSocket)    │                   │
│  └────────────┼──────────────┘ └────────┼───────┘             │
│               │                          │                      │
└───────────────┼──────────────────────────┼──────────────────────┘
                │                          │
                │ host.docker.internal    │
                │                          │
┌───────────────▼──────────────────────────▼──────────────────┐
│                  Docker Network                             │
│                                                              │
│  ┌──────────────────────────────────────────────────┐     │
│  │       MCP Router Container (FastAPI)              │     │
│  │       Port: 8000                                  │     │
│  │                                                    │     │
│  │  EXTERNAL_MCPS:                                   │     │
│  │  - ws://host.docker.internal:9001 (paddleocr)    │     │
│  │  - ws://host.docker.internal:9002 (office-word)  │     │
│  └──────────────────────────────────────────────────┘     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## ✅ 已完成的工作

### 1. MCP Proxy 双模式支持
**文件**: `mcp/proxy/src/mcp_proxy.py`

**功能**:
- ✅ **进程模式** (`type: process`): 启动本地 stdio MCP 进程（开发环境）
- ✅ **容器模式** (`type: docker`): 连接 Docker 容器中的 stdio MCP（生产环境）

**关键类**:
- `MCPServerWrapper`: 支持 process 和 docker 两种类型
- `DockerContainerManager`: Docker 容器管理（通过 `docker exec` 连接）

### 2. Docker Compose 配置
**文件**: `docker-compose.mcp-servers.yml`

**内容**:
```yaml
services:
  paddleocr-mcp:
    build: ./mcp/servers/paddleocr
    image: paddleocr-mcp:latest
    container_name: paddleocr-mcp
    restart: unless-stopped
    # 不暴露端口 - 通过 stdio 与 MCP Proxy 通信
    environment:
      - PYTHONUNBUFFERED=1
      - PADDLEOCR_MCP_PIPELINE=OCR
    resources:
      limits:
        cpus: '2'
        memory: 2G

  office-word-mcp:
    build: ./mcp/servers/office-word
    image: office-word-mcp:latest
    container_name: office-word-mcp
    restart: unless-stopped
    resources:
      limits:
        cpus: '1'
        memory: 512M
```

### 3. Dockerfile
**文件**:
- `mcp/servers/paddleocr/Dockerfile` ✅
- `mcp/servers/office-word/Dockerfile` ✅ (已存在)

### 4. 配置文件更新
**文件**: `mcp/proxy/config/mcp-proxy-config.yml`

**两种模式配置**:
```yaml
# 方式 1: 进程模式（开发环境）
servers:
  - name: paddleocr
    type: process  # 启动本地进程
    port: 9001
    cwd: ../../servers/paddleocr
    command: ["python"]
    args: ["-m", "paddleocr_mcp"]

# 方式 2: 容器模式（生产环境）
servers:
  - name: paddleocr
    type: docker  # 连接到 Docker 容器
    port: 9001
    container: paddleocr-mcp  # Docker 容器名称
```

## 🚀 部署方式

### 开发环境（当前使用）
```bash
# 1. 启动 MCP Proxy（进程模式）
cd /Users/kehongwei/workspace/AICMDEngine/mcp/proxy
python src/mcp_proxy.py

# MCP Proxy 会自动启动:
# - paddleocr (端口 9001)
# - office-word (端口 9002)
```

### 生产环境（容器化部署）
```bash
# 1. 启动 MCP servers 容器
cd /Users/kehongwei/workspace/AICMDEngine
docker-compose -f docker-compose.mcp-servers.yml up -d

# 2. 更新 MCP Proxy 配置为容器模式
# 编辑 mcp/proxy/config/mcp-proxy-config.yml
# 将 type: process 改为 type: docker

# 3. 启动 MCP Proxy
cd /Users/kehongwei/workspace/AICMDEngine/mcp/proxy
python src/mcp_proxy.py
```

## ⚠️ 已知问题

### 1. PaddleOCR 依赖复杂
**问题**: PaddlePaddle 和 PaddleOCR 的依赖较重，构建时间长

**解决方案**:
- 方案 A: 使用官方预编译镜像
- 方案 B: 简化依赖，只安装核心包
- 方案 C: 分阶段构建，缓存模型文件

### 2. 容器启动失败
**当前状态**: PaddleOCR 和 Office-Word 容器在重启循环

**原因**:
- PaddleOCR: 缺少 PaddlePaddle 核心库
- Office-Word: 可能需要更多依赖

**下一步**: 需要完善 Dockerfile 或调整部署策略

## 💡 推荐的部署策略

### 策略 1: 混合模式（推荐用于开发）
```
开发环境: MCP Proxy (process 模式) + 本地 MCP 进程
```
**优点**: 简单、快速、易于调试

### 策略 2: 轻量级容器化（推荐用于生产）
```
生产环境: MCP Proxy (docker 模式) + 轻量级 MCP 容器
```
**优点**: 隔离性好、资源可控、易于扩展

**实施建议**:
1. Office-Word MCP: 使用容器（依赖简单）
2. PaddleOCR MCP: 使用进程模式（依赖复杂）或等待官方支持

### 策略 3: 完全容器化（长期目标）
```
全部容器化: MCP Router + MCP Proxy + MCP Servers
```
**优点**: 完全隔离、易于编排（Kubernetes）
**缺点**: 复杂度高、需要解决 Docker-in-Docker 问题

## 📝 后续工作

### 高优先级
1. **修复容器构建**
   - 完善 PaddleOCR Dockerfile
   - 验证 Office-Word 容器
   - 测试容器启动

2. **测试容器模式**
   - 更新配置为 docker 模式
   - 验证 MCP Proxy 连接
   - 端到端测试

3. **创建启动脚本**
   - 一键启动脚本
   - 停止和清理脚本

### 中优先级
4. **健康检查和监控**
   - 容器健康检查
   - MCP Proxy 状态监控
   - 日志聚合

5. **文档完善**
   - 部署指南
   - 故障排查
   - 配置说明

## 🎯 总结

**架构已固定**:
- MCP Proxy 是核心管理层，支持进程和容器两种模式
- MCP Router 通过 WebSocket 连接 MCP Proxy
- 统一的 stdio → WebSocket 转换

**当前状态**:
- ✅ 架构设计完成
- ✅ 代码实现完成
- ⚠️ 容器构建需要完善
- ✅ 开发环境可用（进程模式）

**下一步行动**:
1. 根据实际需求选择部署策略
2. 完善容器化或继续使用进程模式
3. 添加运维工具和文档

---

**创建时间**: 2026-02-26
**版本**: v1.0
