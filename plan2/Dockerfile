# Copyright 2025 Joinkey Software. All rights reserved.

# Vite + React 前端应用 Dockerfile for plan2
# 多阶段构建：构建阶段 + 生产阶段

ARG NODE_BASE_IMAGE=node:20-alpine
ARG NGINX_BASE_IMAGE=nginx:alpine

# ===== 构建阶段 =====
FROM ${NODE_BASE_IMAGE} AS builder

WORKDIR /app

# 复制package文件并安装依赖
COPY package*.json package-lock.json ./
RUN npm ci

# 复制源代码并构建
COPY . .
RUN npm run build

# ===== 生产阶段 =====
FROM ${NGINX_BASE_IMAGE} AS production

# 安装curl用于健康检查
RUN apk add --no-cache curl

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 创建nginx配置文件支持SPA路由和API代理
RUN cat > /etc/nginx/conf.d/default.conf << 'EOF'
server {
    listen 5122;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # SPA路由支持
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API代理到mcp-router
    location /api/ {
        proxy_pass http://mcp-router:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 暴露端口
EXPOSE 5122

# 启动nginx
CMD ["nginx", "-g", "daemon off;"]
