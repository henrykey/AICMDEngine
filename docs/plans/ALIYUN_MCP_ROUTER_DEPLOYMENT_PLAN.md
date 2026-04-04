# AIPlanner Aliyun MCP Router Deployment Plan

## 1. Goal

为 `AIPlanner` 子项目建立一套独立、可实际执行的阿里云部署方案，部署目标为：

- 目标主机：`aliapp`
- 公网入口：`bridge.joinkey.com.cn`
- 对外只暴露 `plan2`
- `mcp-router` 不直接暴露公网
- `mcp-proxy` 以 host 服务方式运行
- MCP 服务按能力拆分为 host-only 与 dockerized 两类

该方案只定义部署架构、职责边界、目录组织、配置策略和实施步骤，不在本文件中直接实现脚本。

## 2. Scope

### 2.1 Included

- `mcp-router`
- `plan2`
- `mcp/proxy`
- `mcp/servers/paddleocr`
- `mcp/servers/office-word`
- `mcp/servers/PDF2MDEnhanced`
- `mcp/servers/PageIndex`
- 对应部署脚本、systemd 服务、配置模板、Bridge Nginx 配置模板

### 2.2 Excluded

- `ui/` 旧前端
- `mcp/servers/PDF2MD`
  - 已废弃
  - 不进入部署体系
- Membership 主项目部署
  - 仅作为外部依赖服务
- MongoDB / Redis / Kafka / Elasticsearch / Membership / Object Storage 的资源创建
  - 这些资源视为前置已存在

## 3. Deployment Principles

### 3.1 Boundary

`AIPlanner` 的部署目录只负责：

- 构建并部署 AIPlanner 自身容器
- 安装并管理 `mcp-proxy` host 服务
- 上传和分发运行时配置
- 验证 AIPlanner 运行依赖可达

不负责：

- 部署 Membership
- 部署 MongoDB
- 部署对象存储
- 部署基础 Kafka/Redis/ES

### 3.2 Transport Strategy

MCP 服务分两类：

1. `host-only via mcp-proxy`
- 适用于只能可靠通过 stdio 接入的 MCP 服务
- 由 `mcp-proxy` 拉起本地进程并对外暴露 HTTP/SSE

2. `dockerized HTTP MCP`
- 适用于原生支持 HTTP/SSE 的 MCP 服务
- 由 Docker Compose 直接部署
- `mcp-router` 通过容器网络访问

### 3.3 Configuration Strategy

LLM 配置优先级：

1. MongoDB 当前激活配置
2. 环境变量兜底

部署文件和脚本必须遵循这个优先级，不允许把固定 API key 硬编码进部署模板。

## 4. Target Topology

### 4.1 External Traffic

公网用户访问路径：

`Browser -> bridge nginx -> aliapp:5122 -> plan2`

### 4.2 Internal Traffic

AIPlanner 内部访问路径：

- `plan2 -> mcp-router:8000`
- `mcp-router -> host mcp-proxy:9001/9002`
- `mcp-router -> docker MCPs:9010/9011`
- `mcp-router -> membership-api:8080`
- `mcp-router -> MongoDB`

### 4.3 Exposure Rules

建议开放原则：

- 公网：
  - 仅 `bridge` 提供 `plan2` 域名入口
- `aliapp` 对外：
  - 不直接暴露 `8000`
  - 不直接暴露 `9001/9002/9010/9011`
  - `5122` 仅允许来自 `bridge` 或 WG 网段

## 5. Runtime Components

### 5.1 Host Service

#### `mcp-proxy`

职责：

- 读取代理配置
- 启动 stdio MCP 子进程
- 将 stdio MCP 暴露为 HTTP/SSE / streamable-http

管理方式：

- `systemd`

建议服务名：

- `aiplanner-mcp-proxy.service`

### 5.2 Docker Services

#### `mcp-router`

职责：

- AIPlanner 后端主服务
- 聚合内建 MCP 与外部 MCP
- 提供 `/v1/*`、`/api/llm/*`、`/api/design/*`、`/v1/mcp/*`

暴露端口：

- 宿主机 `8000`

访问策略：

- 不对公网开放
- 仅供 `plan2`、WG 或本机访问

#### `plan2`

职责：

- AIPlanner 前端
- 运行时通过 `/config.json` 获取 API 基础地址
- 容器内 Nginx 将 `/api/` 代理到 `mcp-router`

暴露端口：

- 宿主机 `5122`
- 容器内 `5122`

#### `pdf2md-enhanced`

职责：

- 新版 PDF 页面任务化处理

部署方式：

- Docker

端口：

- `9010`

#### `pageindex`

职责：

- 文档页索引/向量外检索能力

部署方式：

- Docker

端口：

- `9011`

### 5.3 Proxy-managed MCPs

#### `paddleocr`

部署方式：

- 由 `mcp-proxy` 管理

代理端口：

- `9001`

#### `office-word`

部署方式：

- 由 `mcp-proxy` 管理

代理端口：

- `9002`

## 6. Port Plan

| Component | Host Port | Exposure | Notes |
| --- | --- | --- | --- |
| plan2 | 5122 | bridge/WG | Public entry via bridge |
| mcp-router | 8000 | private only | No direct public exposure |
| mcp-proxy/paddleocr | 9001 | private only | Accessed by router |
| mcp-proxy/office-word | 9002 | private only | Accessed by router |
| pdf2md-enhanced | 9010 | private only | Accessed by router |
| pageindex | 9011 | private only | Accessed by router |

说明：

- 不引入新的宿主机端口号
- 保持与现有项目约定一致
- 若端口冲突，由用户明确指定覆盖，不由脚本擅自修改默认端口

## 7. Config Model

### 7.1 Root Deployment Env

建议新增：

- `AIPlanner/deploy/env.aliyun.example`

用途：

- 作为统一部署入口配置
- 同时驱动 Docker Compose 与 `mcp-proxy` 模板渲染

建议至少包含：

- `APP_HOST=aliapp`
- `REMOTE_DIR=/opt/AICMDEngine`
- `ROUTER_HOST_PORT=8000`
- `PLAN2_HOST_PORT=5122`
- `PADDLEOCR_PROXY_PORT=9001`
- `OFFICE_WORD_PROXY_PORT=9002`
- `PDF2MD_ENHANCED_HOST_PORT=9010`
- `PAGEINDEX_HOST_PORT=9011`
- `MONGO_HOST`
- `MONGO_PORT`
- `DATABASE_NAME`
- `MEMBERSHIP_SERVICE_URL`
- `JWT_SECRET_KEY`
- `LOG_LEVEL`

### 7.2 Router Config

`mcp-router` 使用：

- `.env`
- `EXTERNAL_MCPS` YAML 字符串

部署时应通过模板生成，而不是手工内联在最终 compose 中。

建议将外部 MCP 定义抽离成模板文件，例如：

- `deploy/router.external_mcps.aliyun.yml.tpl`

生成后注入：

- `EXTERNAL_MCPS=$(cat rendered.yml)`

或在 compose 中通过 env_file 注入多行 YAML。

### 7.3 Proxy Config

建议新增模板：

- `deploy/mcp-proxy-config.aliyun.yml`

内容只保留：

- `paddleocr`
- `office-word`

要求：

- 不允许出现开发机绝对路径
- 不允许硬编码 API key
- 子进程命令路径必须基于远端实际目录
- 通过环境变量传递必要凭据

### 7.4 LLM Config

原则：

- MongoDB 为主
- 环境变量为 fallback

因此：

- `mcp-router` 保留 `OPENAI_*` / `DEEPSEEK_*` / `QWEN_*` 等兜底变量
- `mcp-proxy` 若需给子进程兜底，也从远端 `.env` 注入
- 不在 `mcp-proxy-config.yml` 中写死密钥

## 8. Packaging Strategy

### 8.1 Docker Images

建议构建这些镜像：

- `aiplanner-mcp-router`
- `aiplanner-plan2`
- `aiplanner-pdf2md-enhanced`
- `aiplanner-pageindex`

可选：

- 若后续 `paddleocr` 或 `office-word` 可稳定 HTTP 化，再纳入镜像体系

### 8.2 Host Artifacts

需要打包/上传：

- `mcp/proxy/`
- 代理配置模板渲染结果
- `systemd` service 文件
- 启停辅助脚本

## 9. Deployment Directory Layout on Aliapp

建议远端目录：

- `/opt/AICMDEngine`

建议结构：

```text
/opt/AICMDEngine
├── .env
├── docker-compose.mcp.yml
├── images/
│   └── aiplanner-images.tar.gz
├── proxy/
│   ├── src/
│   ├── requirements.txt
│   ├── config/
│   │   └── mcp-proxy-config.yml
│   └── venv/    # 若采用远端本机虚拟环境
├── systemd/
│   └── aiplanner-mcp-proxy.service
└── plan2/
    └── config.json   # 若采用运行时配置覆盖
```

## 10. Systemd Plan for `mcp-proxy`

建议 systemd 方式：

- `WorkingDirectory=/opt/AICMDEngine/proxy`
- 使用固定 Python 虚拟环境
- `ExecStart=/opt/AICMDEngine/proxy/venv/bin/python -m src`
- `EnvironmentFile=/opt/AICMDEngine/.env`
- `Restart=always`

启动前置：

- 若 `venv` 不存在，部署脚本负责创建
- 安装 `requirements.txt`

日志：

- 直接交给 `journalctl`
- 不额外自己重定向文件，除非后续有日志采集需要

## 11. Docker Compose Plan

建议新增：

- `AIPlanner/deploy/docker-compose.mcp.yml`

只包含：

- `mcp-router`
- `plan2`
- `pdf2md-enhanced`
- `pageindex`

不包含：

- `mcp-proxy`
- `paddleocr`
- `office-word`
- `PDF2MD`

原因：

- `mcp-proxy` 是 host-only
- `paddleocr` / `office-word` 当前策略是由 `mcp-proxy` 管 stdio
- `PDF2MD` 已废弃

## 12. Bridge Nginx Plan

建议新增模板：

- `AIPlanner/deploy/nginx.bridge.plan2.aliyun.conf.template`

职责：

- `server_name bridge.joinkey.com.cn` 下某个路径或子域转发到 `aliapp:5122`

建议入口策略二选一：

1. 子域
- `plan2.joinkey.com.cn -> aliapp:5122`

2. 路径
- `bridge.joinkey.com.cn/plan2/ -> aliapp:5122`

如果与 membership 现有入口共存，我更建议子域，路由更清晰。

## 13. Preflight Checks

建议新增：

- `AIPlanner/deploy/preflight-resources.sh`

检查内容：

- MongoDB 可连且目标 DB 可访问
- Membership API 可达
- `bridge` 到 `aliapp:5122` 路径可达性
- 端口未冲突：
  - `8000`
  - `5122`
  - `9001`
  - `9002`
  - `9010`
  - `9011`

注意：

- 不负责创建资源
- 只负责检测可用性和冲突

## 14. Deployment Script Plan

建议新增：

- `AIPlanner/deploy/deploy.sh`

支持动作：

1. `prepare`
- 构建 Docker 镜像
- 导出镜像 tar.gz
- 渲染 `docker-compose.mcp.yml`
- 渲染 `mcp-proxy-config.yml`
- 生成 systemd service 文件

2. `upload`
- 上传镜像包
- 上传 `.env`
- 上传 compose 文件
- 上传 proxy 代码与配置
- 上传 systemd service 文件

3. `deploy`
- 远端 `docker load`
- `docker compose up -d`
- 准备/更新 proxy venv
- 安装依赖
- 安装/刷新 systemd service
- `systemctl restart aiplanner-mcp-proxy`

4. `all`
- 串联以上步骤

### 14.1 Important Constraint

和主项目一致：

- 默认不部署基础设施
- 默认不拉不相关资源镜像
- 默认不擅自改端口

## 15. Rollout Plan

建议实施顺序：

### Phase 1

只落地文档与部署骨架：

- `deploy/README.md`
- `docker-compose.mcp.yml`
- `.env` 模板
- `systemd` 模板
- `nginx` 模板

### Phase 2

落地 `mcp-proxy` host 部署：

- 配置模板
- venv 安装逻辑
- service 管理

### Phase 3

落地 `mcp-router` + `plan2` + HTTP MCP 容器部署：

- 镜像构建
- tar 打包
- 远端 compose 启动

### Phase 4

联调 Bridge 入口：

- bridge nginx
- 运行时 `plan2` 配置
- API 路由验证

## 16. Risks

### 16.1 Path Risk

`mcp-proxy` 当前配置依赖开发机绝对路径，必须模板化，否则无法迁移到 `aliapp`。

### 16.2 Secret Risk

当前 proxy 配置中有硬编码 key，必须去掉，否则部署文档和仓库都会继续泄露敏感信息。

### 16.3 Mixed Runtime Risk

host 进程与容器混合部署会带来：

- 日志入口不同
- 生命周期管理不同
- 依赖安装方式不同

需要在 README 中明确区分。

### 16.4 Frontend Runtime Config Risk

`plan2` 目前支持 `/config.json` 运行时配置，这是优点。  
部署时应优先利用这一点，而不是把 API 地址写死进构建产物。

## 17. Recommended Final Architecture

最终建议架构：

- `aliapp`
  - `systemd`: `aiplanner-mcp-proxy`
  - `docker compose`: `mcp-router`, `plan2`, `pdf2md-enhanced`, `pageindex`
- `bridge`
  - nginx only
  - public entry only for `plan2`

MCP 接入分层：

- `paddleocr` -> `mcp-proxy`
- `office-word` -> `mcp-proxy`
- `pdf2md-enhanced` -> direct docker HTTP MCP
- `pageindex` -> direct docker HTTP MCP

## 18. Next Step

本计划确认后，下一步实施内容应为：

1. 在 `AIPlanner/deploy/` 下创建部署骨架文件
2. 先实现文档、模板和 compose
3. 再实现 `mcp-proxy` 的 systemd 部署
4. 最后实现统一 `deploy.sh`
