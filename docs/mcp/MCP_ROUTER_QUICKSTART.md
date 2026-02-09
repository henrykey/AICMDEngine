# MCP Router - 快速启动指南

## 概述

MCP Router服务提供WebSocket端点，使外部MCP客户端能够访问内部MCP服务器工具。

## 端点

- **WebSocket**: `ws://localhost:8000/mcp/v1?token=JWT_TOKEN`
- **健康检查**: `http://localhost:8000/health`

## 启动步骤

### 1. 配置环境变量

```bash
# 复制配置模板
cp .env.mcp-router.template .env

# 编辑配置文件，设置必需的环境变量
nano .env
```

**必需配置**:
```bash
JWT_SECRET_KEY=your-secret-key-here  # 必须设置
```

### 2. 生成测试JWT Token

```python
import jwt
import time

token = jwt.encode(
    {
        "sub": "test-client",
        "name": "Test MCP Client",
        "scopes": ["mcp:*"],
        "exp": int(time.time()) + 3600,
        "iat": int(time.time())
    },
    "your-secret-key-here"
)

print(token)
```

### 3. 启动服务

```bash
# 方式1: 直接运行
python -m src.main

# 方式2: Docker
docker-compose -f docker-compose.mcp-router.yml up -d
```

### 4. 测试连接

使用websocat测试：
```bash
# 安装websocat
cargo install websocat

# 连接（使用生成的token）
websocat "ws://localhost:8000/mcp/v1?token=YOUR_JWT_TOKEN"

# 发送initialize消息
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}

# 请求工具列表
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

## 生产部署

### 使用Nginx反向代理

1. 生成SSL证书（使用Let's Encrypt）
```bash
certbot certonly --standalone -d mcp.yourdomain.com
```

2. 更新Nginx配置
```bash
# 编辑配置文件
nano deploy/nginx/mcp-router.conf

# 修改域名和证书路径
server_name mcp.yourdomain.com;
ssl_certificate /etc/nginx/ssl/fullchain.pem;
ssl_certificate_key /etc/nginx/ssl/privkey.pem;
```

3. 启动服务
```bash
docker-compose -f docker-compose.mcp-router.yml up -d
```

## 常见问题

### JWT验证失败
- 确认JWT_SECRET_KEY正确
- 确认token包含mcp权限scopes

### WebSocket连接失败
- 检查防火墙设置
- 确认端口8000开放
- 查看服务日志

### 工具调用失败
- 确认MCP Registry已初始化
- 检查工具名称格式：`mcp_server.tool_name`

## 监控和日志

```bash
# 查看日志
docker-compose -f docker-compose.mcp-router.yml logs -f mcp-router

# 查看连接数
curl http://localhost:8000/health
```

## 下一步

- [ ] 配置生产环境的JWT密钥
- [ ] 设置SSL证书
- [ ] 配置监控和告警
- [ ] 压力测试和性能优化
