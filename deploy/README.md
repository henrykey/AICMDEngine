# AIPlanner Aliyun Deploy Skeleton

本目录用于承接 `docs/plans/ALIYUN_MCP_ROUTER_DEPLOYMENT_PLAN.md` 的阿里云部署骨架。

当前目录提供阿里云部署骨架和首轮试跑所需脚本。

## 当前落地内容

- `docker-compose.mcp.yml`
  - AIPlanner 应用侧 Compose 骨架
  - 包含 `mcp-router`、`plan2`、`office-word`、`pdf2md-enhanced`、`pageindex`
- `env.aliyun.example`
  - 阿里云部署环境变量模板
  - 同时服务于 Compose、systemd 和配置模板渲染
- `plan2.config.aliyun.json`
  - `plan2` 运行时配置模板
  - 生成后挂载到容器内 `/usr/share/nginx/html/config.json`
- `mcp-proxy.service`
  - `mcp-proxy` 的 systemd 服务模板
  - 仅在显式启用 proxy 部署时使用
- `mcp-proxy-config.aliyun.yml`
  - `mcp-proxy` 的阿里云配置骨架
  - 当前仅保留 `office-word`
  - 仅在显式启用 proxy 部署时使用
- `nginx.bridge.plan2.aliyun.conf.template`
  - `bridge` 侧 Nginx 转发模板
- `preflight-resources.sh`
  - 本地预检脚本骨架
  - 检查端口占用、环境文件、基础连通性
- `deploy.sh`
  - 统一部署入口
  - 提供 `prepare-cache` / `prepare` / `upload` / `deploy` / `all` 动作
- `deploy-remote-build.sh`
  - 独立的“上传源码 -> 远端构建 -> 部署 -> 清理源码”入口
  - 适合弱网/WireGuard 场景，避免上传大镜像归档
  - 支持 `--mirror cn`（国内镜像，清华优先）与 `rsync` 重试上传

## 目标拓扑

公网流量：

`Browser -> bridge nginx -> aliapp:5122 -> plan2`

AIPlanner 内部访问：

- `plan2 -> mcp-router:8000`
- `mcp-router -> aliapp(172.18.157.7) 上的 mcp-proxy:9002`（仅在启用 proxy 时）
- `mcp-router -> docker MCPs:9002/9010/9011`
- `mcp-router -> membership-api:8080`
- `mcp-router -> MongoDB@172.18.157.8:27017`

其中 `membership` 有两层角色：

- 托管登录与鉴权
- 作为 MCP 的主要客户端/消费者

## 约束

- 对外只暴露 `plan2`
- `mcp-router` 不直接暴露公网
- `mcp-proxy` 为可选能力，启用时以 host + `systemd` 方式运行
- 默认不部署 `mcp-proxy`
- `office-word` / `pdf2md-enhanced` / `pageindex` 通过 Docker Compose 部署
- AIPlanner 容器复用已存在的 `membership_default` Docker network，不新建独立 bridge
- 端口是设计常量，不允许改动：
  - `8000` `5122` `9002` `9010` `9011`
- `membership` 负责登录鉴权托管，并作为 MCP 的主要客户端/消费者
- 不在模板里硬编码 API key
- LLM 配置优先读 MongoDB，环境变量仅作为 fallback
- 部署模板中的容器互访一律使用明确内网 IP，不使用 `localhost`

## 当前脚本能力

`deploy.sh` 当前支持：

- `prepare`
  - 自动检查并准备 `linux/amd64` wheelhouse 缓存
  - 生成远端可上传 bundle 到 `deploy/out/`
  - 渲染 `plan2/config.json`
  - 生成远端使用的 image-only Compose 文件
  - 可选 `--build-images` 生成 `images/aiplanner-images.tar.gz`
  - 仅在显式传 `--with-proxy` 时：
    - 渲染 `mcp-proxy` 配置和 systemd 服务文件
    - 复制 `mcp/proxy/src`
    - 复制 `office-word`
- `upload`
  - 通过 `ssh + tar` 把 `deploy/out/` 同步到 `${APP_HOST}:${REMOTE_DIR}`
- `deploy`
  - 远端执行：
    - `docker load`（若存在镜像归档）
    - `docker compose up -d`（可按 `--service` 只拉起指定服务）
    - 仅在显式传 `--with-proxy` 时：
      - proxy venv 初始化
      - proxy / office-word 依赖安装
      - 若 `deploy/cache/wheels` 已准备，则优先离线安装 amd64 wheels
      - systemd 安装与重启 `aiplanner-mcp-proxy`

参数风格与主项目 `membership/deploy/deploy.sh` 对齐：

- `--env-file`
- `--app-host`
- `--remote-dir`
- `--with-proxy`
- `--mirror cn`
- `--service`

其中：

- `--app-host` 为必传
- `--remote-dir` 默认固定为 `/opt/AICMDEngine`
- `--mirror cn` 会为 Docker base image、`pip`、`npm`、`apt`、`apk` 启用国内镜像，默认优先使用清华源
- `--service` 支持 `all`、`mcp`、`mcp-router`、`plan2`、`office-word`、`pdf2md-enhanced`、`pageindex`
- `mcp` 会展开为 `office-word` + `pdf2md-enhanced` + `pageindex`
- `office-word` 与 `--with-proxy` 不能同时使用，因为两者都占用宿主机 `9002`
- `plan2` 的运行时入口地址自动按 `http://<APP_HOST>:<PLAN2_HOST_PORT>` 生成

## 常用命令速查（远端源码构建）

```bash
# 一键全量部署（推荐）
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --app-user root \
  --scope all \
  --mirror cn \
  --upload-method rsync \
  --rsync-bwlimit 2048 \
  --upload-retries 5 \
  --upload-retry-sleep 5 \
  -f \
  all

# 只部署 plan2-ui
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --scope plan2 \
  --mirror cn \
  all

# 只部署 mcp-router
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --scope router \
  --mirror cn \
  all

# 只部署 mcp servers（office-word + pdf2md-enhanced + pageindex）
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --scope mcp \
  --mirror cn \
  all

# 查看运行状态
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  status

# 查看日志
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  logs
```

## 使用指南

### 快速路径（远端源码构建，推荐）

```bash
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --app-user root \
  --scope all \
  --mirror cn \
  --upload-method rsync \
  --rsync-bwlimit 2048 \
  --upload-retries 5 \
  --upload-retry-sleep 5 \
  -f \
  all
```

可选 `--scope`：

- `router`：仅构建/部署 `mcp-router`
- `plan2`：仅构建/部署 `plan2-ui`
- `mcp`：仅构建/部署 `office-word` + `pdf2md-enhanced` + `pageindex`
- `all`：构建/部署全部组件

`deploy-remote-build.sh` 动作说明：

- `build-src`：只生成本地源码包（不上传）
- `upload-src`：上传源码包、`.env`、`docker-compose.mcp.yml`、`plan2/config.json`
- `remote-build`：使用远端已上传源码包执行构建和部署
- `remote-clean`：删除远端源码包
- `all`：`build-src + upload-src + remote-build`

按组件定向部署示例：

```bash
# 仅部署 mcp-router
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --scope router \
  --mirror cn \
  all

# 仅部署 plan2-ui
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --scope plan2 \
  --mirror cn \
  --upload-method rsync \
  all

# 仅部署 mcp servers（office-word + pdf2md-enhanced + pageindex）
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --scope mcp \
  --mirror cn \
  all
```

分步执行示例：

```bash
# 1) 本地打包
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --scope all \
  -f \
  build-src

# 2) 上传产物
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --upload-method rsync \
  --rsync-bwlimit 2048 \
  upload-src

# 3) 远端构建并部署
bash AIPlanner/deploy/deploy-remote-build.sh \
  --env-file AIPlanner/.env.ali \
  --app-host aliapp \
  --scope all \
  --mirror cn \
  remote-build
```

### 前置条件

本地：

- 已准备部署环境文件
  - 可直接使用 `AIPlanner/.env.ali`
  - 或由 `env.aliyun.example` 复制后修改
- 可通过 `ssh aliapp` 免密或正常登录目标主机
- 本地具备：
  - `bash`
  - `python`
  - `docker`
  - `ssh`
  - `tar`

远端 `aliapp`：

- 已安装：
  - `docker`
  - `docker compose`
  - `python3`
  - `python3 -m venv`
- `systemctl`
- `sudo`
- `membership_default` Docker network 已存在
- `membership-api` 已在 `membership_default` 网络内可达
- MongoDB 已在 `172.18.157.8:27017` 可达

### 1. 准备环境文件

推荐直接使用：

```bash
AIPlanner/.env.ali
```

如需从模板生成：

```bash
cp AIPlanner/deploy/env.aliyun.example AIPlanner/deploy/.env
```

然后至少确认这些值：

- `MEMBERSHIP_SERVICE_URL=http://membership-api:8080`
- `MONGODB_URI=mongodb://172.18.157.8:27017/nl_tps?authSource=admin`

### 2. 本地预检

使用 `AIPlanner/.env.ali`：

```bash
bash AIPlanner/deploy/preflight-resources.sh --env AIPlanner/.env.ali
```

如果只想跳过本地端口冲突检查：

```bash
bash AIPlanner/deploy/preflight-resources.sh --env AIPlanner/.env.ali --skip-ports
```

### 3. 生成部署产物

脚本在 `prepare` / `all --build-images` 时会自动准备 `linux/amd64` Python 预存储包。
默认不包含 proxy 相关 wheelhouse；只有显式传 `--with-proxy` 时才会准备 proxy 依赖。
如显式传 `--mirror cn`，构建和依赖下载会优先使用国内镜像，默认优先走清华源。

如需单独预热缓存，也可以显式执行：

```bash
bash AIPlanner/deploy/deploy.sh \
  prepare-cache \
  --env-file AIPlanner/.env.ali \
  --mirror cn
```

缓存目录：

- `AIPlanner/deploy/cache/wheels/`
- `AIPlanner/.wheelhouse/mcp-router/`
- `AIPlanner/mcp/servers/PageIndex/.wheelhouse/`
- `AIPlanner/mcp/servers/PDF2MDEnhanced/.wheelhouse/`

只生成 bundle，不构建镜像：

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  prepare \
  --mirror cn
```

生成 bundle 并同时构建镜像归档：

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  prepare --build-images --mirror cn
```

如需同时打包 `mcp-proxy`：

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  prepare --build-images --with-proxy --mirror cn
```

只构建并打包指定服务，例如 `office-word` + `pageindex`：

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  prepare --build-images --mirror cn --service office-word,pageindex
```

说明：

- `prepare`：若缓存缺失，会自动下载 amd64 wheels
- `prepare --build-images`：默认复用已有缓存，不会强制重下
- `prepare/deploy/all` 可通过 `--service` 限制本次构建、打包和拉起的服务范围
- 如需强制重新下载缓存，显式加：
  - `--refresh-cache`
- 若本机下载官方源过慢，可直接设置标准代理变量：
  - `HTTP_PROXY`
  - `HTTPS_PROXY`
  - `ALL_PROXY`
  - `NO_PROXY`
- 如果代理地址写的是 `127.0.0.1` 或 `localhost`，脚本会在下载容器里自动改写成 `host.docker.internal`
- 若基础镜像需要改走代理仓库，可设置：
  - `CACHE_PYTHON_311_IMAGE`
  - `CACHE_PYTHON_312_IMAGE`
  - `PLAN2_NODE_BASE_IMAGE`
  - `PLAN2_NGINX_BASE_IMAGE`
  例如改成你自己的镜像代理前缀，而不是默认的官方镜像名

生成结果位于：

- `AIPlanner/deploy/out/`

### 4. 上传到 aliapp

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  upload
```

### 5. 在 aliapp 执行部署

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  deploy --service office-word,pageindex
```

如需同时安装并启动 `mcp-proxy`：

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  deploy --with-proxy
```

或直接串联执行：

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  all --build-images --mirror cn
```

如需完整执行并附带 `mcp-proxy`：

```bash
bash AIPlanner/deploy/deploy.sh \
  --env-file AIPlanner/.env.ali \
  --app-host 172.18.157.7 \
  all --build-images --with-proxy
```

### 6. 部署后验证

检查容器：

```bash
ssh aliapp 'cd /opt/AICMDEngine && docker compose -f docker-compose.mcp.yml ps'
```

检查 `mcp-proxy` 服务（仅在使用 `--with-proxy` 时）：

```bash
ssh aliapp 'sudo systemctl status aiplanner-mcp-proxy.service --no-pager --full'
```

检查 `mcp-router`：

```bash
ssh aliapp 'curl -fsS http://127.0.0.1:8000/health'
```

检查 `plan2`：

```bash
ssh aliapp 'curl -I http://127.0.0.1:5122'
```

检查 `plan2` 运行时配置：

```bash
ssh aliapp 'cat /opt/AICMDEngine/plan2/config.json'
```

### 7. Bridge 联调

Bridge 侧 Nginx 模板：

- `AIPlanner/deploy/nginx.bridge.plan2.aliyun.conf.template`

验证：

```bash
curl -I https://plan2.joinkey.com.cn
```

## 约定中的远端目录

建议远端根目录：

`/opt/AICMDEngine`

建议结构：

```text
/opt/AICMDEngine
├── .env
├── plan2/
│   └── config.json
├── data/
│   └── pdf2md-enhanced/
│       ├── input/
│       └── output/
├── docker-compose.mcp.yml
├── cache/
│   └── wheels/
│       ├── mcp-router/
│       ├── pageindex/
│       └── pdf2md-enhanced/
├── images/
│   └── aiplanner-images.tar.gz
```

启用 `--with-proxy` 后，远端还会增加：

```text
/opt/AICMDEngine/proxy
├── src/
├── requirements.txt
├── servers/
│   └── office-word/
├── config/
│   └── mcp-proxy-config.yml
├── systemd/
│   └── aiplanner-mcp-proxy.service
└── venv/
```

## 当前不是最终实现的部分

- 未实现 bridge Nginx 的自动下发
- 未实现远端资源预检和回滚
- 未处理生产证书、白名单、防火墙和实际域名切换

后续阶段应在此骨架上继续补齐脚本与校验逻辑，而不是重新发明目录和配置模型。
