# AIPlanner Aliyun Deploy Skeleton Summary

## 1. Background

本次工作基于 `docs/plans/ALIYUN_MCP_ROUTER_DEPLOYMENT_PLAN.md`，先落 `deploy/` 部署骨架，不进入全量远端部署实现。

目标是先把部署结构、目录、端口、组件边界和脚本动作面固定住，避免后续边写边改。

## 2. Scope Completed

本次已落地以下文件：

- `deploy/README.md`
- `deploy/docker-compose.mcp.yml`
- `deploy/env.aliyun.example`
- `deploy/mcp-proxy.service`
- `deploy/mcp-proxy-config.aliyun.yml`
- `deploy/nginx.bridge.plan2.aliyun.conf.template`
- `deploy/preflight-resources.sh`
- `deploy/deploy.sh`

同时 `deploy/out/` 已可由 `prepare` 动作生成远端可上传 bundle。

## 3. Fixed Architecture Decisions

### 3.1 Exposure Boundary

公网入口保持：

`Browser -> bridge nginx -> aliapp:5122 -> plan2`

对外只暴露 `plan2`。

以下端口不对公网开放：

- `8000`
- `9001`
- `9002`
- `9010`
- `9011`

### 3.2 Runtime Split

运行时职责已经固定为：

- `plan2`: Docker
- `mcp-router`: Docker
- `pdf2md-enhanced`: Docker
- `pageindex`: Docker
- `mcp-proxy`: host + `systemd`
- `paddleocr`: 由 `mcp-proxy` 拉起
- `office-word`: 由 `mcp-proxy` 拉起

### 3.3 Membership Role

`membership` 的角色已明确写入部署骨架：

- 托管登录与鉴权
- 作为 MCP 的主要客户端/消费者

这意味着部署侧不能把 AIPlanner 当成独立认证边界，相关配置和连通性检查都必须保留对 `membership` 的依赖。

### 3.4 Port Policy

端口被视为设计常量，不允许改动：

- `mcp-router`: `8000`
- `plan2`: `5122`
- `paddleocr`: `9001`
- `office-word`: `9002`
- `pdf2md-enhanced`: `9010`
- `pageindex`: `9011`

这项约束已体现在：

- `deploy/docker-compose.mcp.yml`
- `deploy/env.aliyun.example`
- `deploy/preflight-resources.sh`

其中 `preflight-resources.sh` 会校验这些端口值是否仍然等于设计值，防止后续被误改。

## 4. File-Level Summary

### 4.1 `deploy/docker-compose.mcp.yml`

已固定 Compose 范围，只包含：

- `mcp-router`
- `plan2`
- `pdf2md-enhanced`
- `pageindex`

并明确：

- `mcp-router` 通过 `host.docker.internal:9001/9002` 访问 host 上的 `mcp-proxy`
- `mcp-router` 通过容器网络访问 `pdf2md-enhanced:9010` 和 `pageindex:9011`
- 宿主机端口映射采用固定值，不再允许通过 env 改写设计端口

### 4.2 `deploy/mcp-proxy-config.aliyun.yml`

该配置只保留：

- `paddleocr`
- `office-word`

并且已经去除：

- 开发机绝对路径
- 明文 API key
- 已废弃的 `PDF2MD`

### 4.3 `deploy/mcp-proxy.service`

已固定 systemd 运行方式：

- `WorkingDirectory=/opt/aiplanner/proxy`
- `EnvironmentFile=/opt/aiplanner/.env`
- `ExecStart=/opt/aiplanner/proxy/venv/bin/python -m src`
- `Restart=always`

### 4.4 `deploy/nginx.bridge.plan2.aliyun.conf.template`

已提供 `bridge` 侧 Nginx 模板骨架，当前采用子域方案：

- `plan2.joinkey.com.cn -> aliapp:5122`

这与部署计划中的推荐方向一致，路由边界比路径转发更清晰。

### 4.5 `deploy/preflight-resources.sh`

已实现本地预检骨架，覆盖：

- 环境文件加载
- 必需文件检查
- 固定端口值校验
- 可选本地端口占用检查
- MongoDB URI 形态检查
- Membership URL 可达性检查
- bridge 路径提示

说明：

- 它不创建资源
- 它不修改远端状态
- `prepare` 默认跳过本地端口占用检查，以免影响开发机生成骨架产物

### 4.6 `deploy/deploy.sh`

已固定动作面：

- `prepare`
- `upload`
- `deploy`
- `all`

当前状态：

- `prepare` 可生成 `deploy/out/` 远端 bundle
- `prepare --build-images` 可构建并导出镜像归档
- `upload` 可通过 `ssh + tar` 上传 bundle 到 `aliapp`
- `deploy` 可在远端执行镜像加载、`docker compose up -d`、proxy venv 初始化、依赖安装和 systemd 刷新

## 5. Validation Performed

本次已完成以下验证：

1. `deploy/docker-compose.mcp.yml` YAML 可正常解析
2. `deploy/mcp-proxy-config.aliyun.yml` YAML 可正常解析
3. `bash deploy/preflight-resources.sh --env deploy/env.aliyun.example --skip-ports` 可正常执行
4. `bash deploy/deploy.sh prepare` 可正常生成 `deploy/out/`
5. `deploy/out/` 已包含 proxy runtime、host-only MCP 源码和远端用数据目录

已确认 `deploy/out/` 当前可生成：

- `.env`
- `data/pdf2md-enhanced/input`
- `data/pdf2md-enhanced/output`
- `docker-compose.mcp.yml`
- `proxy/config/mcp-proxy-config.yml`
- `proxy/systemd/aiplanner-mcp-proxy.service`
- `proxy/src`
- `proxy/servers/paddleocr`
- `proxy/servers/office-word`
- `images/README.txt`
- `MANIFEST.txt`

## 6. Known Gaps

当前仍未实现：

- bridge Nginx 实机联调
- 生产证书、防火墙、来源白名单
- 远端依赖安装失败后的回滚
- `paddleocr` 系统级依赖的宿主机预装自动化
- 远端环境完整预检

因此当前状态应被视为：

- 部署结构已定
- 实施入口已定
- 远端执行逻辑已接通
- 实机环境适配仍待补

而不是“已经在任意 aliapp 主机上零调整可直接上线”。

## 7. Risks Already Reduced

本次骨架已经实质降低了几类风险：

### 7.1 Port Drift Risk

之前端口仍有被环境变量覆写的空间，现在已固定为设计常量，并在预检中做硬校验。

### 7.2 Secret Leakage Risk

新的 `mcp-proxy` 阿里云配置骨架不再携带明文 key，也不再延续开发机配置中的敏感信息写法。

### 7.3 Path Migration Risk

proxy 配置已切换为远端目录模型，不再依赖本地开发机绝对路径。

### 7.4 Runtime Boundary Ambiguity

混合运行时边界已经写清：

- 哪些走 Docker
- 哪些走 host + systemd
- 谁是公网入口
- 谁只允许内网访问

## 8. Recommended Next Step

下一阶段建议继续按原计划推进：

1. 在真实 `aliapp` 上执行一次 `prepare -> upload -> deploy`
2. 确认远端 `docker compose`、`systemd`、`python3`、`sudo` 可用
3. 根据 `paddleocr` 实际宿主机环境补系统依赖
4. 联调 `bridge -> aliapp:5122 -> plan2 -> mcp-router -> membership`

推进过程中应继续保持以下约束不变：

- 端口不得更改
- `membership` 负责登录鉴权托管
- `membership` 是 MCP 的主要客户端/消费者
- `mcp-router` 不直接暴露公网
- `mcp-proxy` 继续走 host + systemd
