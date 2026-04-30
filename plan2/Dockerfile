# Copyright 2025 Joinkey Software. All rights reserved.

# Vite + React 前端应用 Dockerfile for plan2
# 多阶段构建：构建阶段 + 生产阶段

ARG NODE_BASE_IMAGE=node:20-alpine
ARG NGINX_BASE_IMAGE=nginx:alpine
ARG NPM_REGISTRY=
ARG ALPINE_MIRROR=

# ===== 构建阶段 =====
FROM ${NODE_BASE_IMAGE} AS builder

WORKDIR /app

# 复制package文件并安装依赖
COPY package*.json package-lock.json ./
RUN if [ -n "${NPM_REGISTRY}" ]; then \
            npm ci --registry "${NPM_REGISTRY}"; \
        else \
            npm ci; \
        fi

# 复制源代码并构建
COPY . .
RUN npm run build

# ===== 生产阶段 =====
FROM ${NGINX_BASE_IMAGE} AS production

ARG ALPINE_MIRROR=

# 安装curl用于健康检查
RUN if [ -n "$ALPINE_MIRROR" ]; then \
            sed -i "s|https\?://dl-cdn.alpinelinux.org/alpine|https://$ALPINE_MIRROR|g" /etc/apk/repositories; \
        fi \
        && apk add --no-cache curl

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# Default to Docker Desktop host gateway for local development.
ENV MEMBERSHIP_UPSTREAM=http://host.docker.internal:8080

# Create nginx template so upstreams can be configured at container start.
RUN mkdir -p /etc/nginx/templates \
    && cat > /etc/nginx/templates/default.conf.template << 'EOF'
upstream mcp_router {
    server mcp-router:8000;
    keepalive 16;
}

server {
    listen 5122;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # SPA路由支持
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API代理到mcp-router (/api/* 路由: LLM、design等)
    location /api/ {
        proxy_pass http://mcp_router;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }

    # API代理到mcp-router (/v1/* 路由: tasks、mcp、auth等)
    location /v1/ {
        proxy_pass http://mcp_router;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 300s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
    }

    # Membership API proxy for unified login endpoints
    location /v2/ {
        proxy_pass ${MEMBERSHIP_UPSTREAM};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 300s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;
    }
}
EOF

# 暴露端口
EXPOSE 5122

# 启动nginx
CMD ["nginx", "-g", "daemon off;"]
