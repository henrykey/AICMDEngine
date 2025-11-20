# 成员管理系统对外使用手册

> 版本：v2.4（2025-09-29）  
> 受众：需要与成员管理系统集成的业务系统、平台服务与运维团队  
> 参考资料：`README.md`、`membership_openapi.yaml`、`docs/audit_upgrade_plan_v2.4*.md` 等

---

## 1. 手册定位与阅读路径

| 章节 | 目的 | 适用角色 |
| --- | --- | --- |
| 2-3 | 了解系统边界、部署形态与接入前置条件 | 架构师、项目经理 |
| 4 | 理解认证、租户与安全策略 | 安全、接入开发 |
| 5-7 | 查阅 API 规范、示例与场景化流程 | 开发、测试 |
| 8 | 异步审计 / 事件流集成 | 集成平台、数据团队 |
| 9 | 工具链 & 验收、测试指引 | QA、SRE |

---

## 2. 系统总览

### 2.1 模块拓扑

```
┌──────────────────────┐        ┌──────────────────────┐
│ membership-admin-ui  │◀──────▶│ membership-api (REST)│
└──────────────────────┘        └──────────┬───────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              │                            │                            │
   ┌──────────▼─────────┐     ┌────────────▼──────────┐     ┌───────────▼─────────┐
   │ membership-repo     │     │ membership-auth       │     │ membership-audit     │
   │ (PostgreSQL + RLS)  │     │ (LDAP + JWT)          │     │ (Kafka + Mongo + CDC)│
   └──────────┬─────────┘     └────────────┬──────────┘     └───────────┬─────────┘
              │                             │                           │
       PostgreSQL 16                Redis 7 / Kafka 3.8          Kafka / MongoDB 6
```

### 2.2 核心能力

- **多租户隔离**：所有 API 通过 `X-Tenant-ID` 头或 Token Claim 识别租户，DB 层启用 RLS。
- **组织 + 岗位模型**：闭包表 + 存储过程（参见 `ORG_HIERARCHY_GUIDE.md`）。
- **角色 / 权限 / 资源**：RBAC + 位图掩码（READ=4，WRITE=2，EXECUTE=1）。
- **AI Agent 虚拟成员**：与人类成员同构建模，支持凭证、策略与运行日志。
- **审计链路**：`audit_outbox` → Debezium → Kafka `membership-server.public.audit_outbox` → MongoDB。
- **可观测性**：Actuator、结构化日志、Prometheus 指标。

---

## 3. 接入前准备

1. **确认场景**：同步成员、角色授权、权限校验、审计取数或 UI 嵌入。
2. **申请资源**：
   - **租户 ID**：由平台运维分配（示例：`1` 或 `default`）。
   - **客户端凭证**：服务间调用使用 `client_id / client_secret`。
   - **测试账号**：默认 `admin/admin123`（可参见 `README.md` “测试环境配置”）。
3. **环境选择**：

| 环境 | 访问入口（默认） | 用途 | 备注 |
| --- | --- | --- | --- |
| Dev | `http://localhost:8080` | 本地开发 / PoC | 可用 docker-compose.test |
| Test | `https://api-test.membership.<corp>` | 联调 / 回归 | 需要 VPN 与 IP 白名单 |
| Prod | `https://api.membership.<corp>` | 生产集成 | 启用完整审计与限流 |

> 真实域名以部署团队发布的 `.env` / `deploy/README.md` 配置为准。

4. **网络白名单**：对外系统需放通 API、Kafka、MongoDB（如仅使用 REST 可忽略后两者）。
5. **数据治理**：明确租户下的数据主系统及同步方向（单向拉取/推送/双向）。

---

## 4. 认证与安全

### 4.1 令牌获取

| 场景 | 接口 | 请求体关键字段 | 说明 |
| --- | --- | --- | --- |
| 用户登录 | `POST /v2/auth/login` | `username`, `password`, `device_id?` | 返回 `LoginResponse`（access/refresh/autologin token） |
| 服务间调用 | `POST /v2/auth/token` | `grant_type=client_credentials`, `client_id`, `client_secret` | 最小权限客户端，便于微服务集成 |
| 密码模式 | `POST /v2/auth/token` | `grant_type=password`, `username`, `password` | 兼容老系统 |
| OTP 设备 | `POST /v2/auth/otp-login` | `username`, `otp_code` | 需要先 `otp-request` |
| 自动登录 | `POST /v2/auth/auto-login` | `auto_login_token`, `device_id` | 供嵌入式客户端使用 |
| Token 刷新 | `POST /v2/auth/token/refresh` | `refresh_token` | 返回新的 access token |

**示例**：

```bash
curl -X POST "$BASE_URL/v2/auth/login" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 1" \
  -d '{
    "username": "admin",
    "password": "admin123",
    "device_id": "portal-prod-01"
  }'
```

### 4.2 必备请求头

| 头部 | 作用 |
| --- | --- |
| `Authorization: Bearer <token>` | 访问令牌，所有受保护的端点必填 |
| `X-Tenant-ID: <long>` | 声明租户，若 Token 中含租户声明可选，但建议显式传递 |
| `X-Request-ID`（自定义） | 便于链路追踪，未内置校验可使用 UUID |
| `Accept-Language` / `lang` | 多语言响应，默认 `zh` |

### 4.3 权限模型

1. **成员 → 角色 → 权限**：推荐通过角色授权，减少直接权限。
2. **范围**：角色与权限均可绑定 `org_id`，只在指定组织及其子节点生效。
3. **位图掩码**：权限值 0-7，使用 `READ=4`、`WRITE=2`、`EXECUTE=1` 组合。
4. **审计**：所有授权、登录、敏感查询都会写入 `audit_outbox`，下游用于合规追踪。

---

## 5. API 使用通则

- **Base Path**：`/v2`；完整规范见 `membership_openapi.yaml` 或运行中 `http(s)://<host>/v3/api-docs`。
- **分页**：`page`（默认 1），`page_size`（默认 20，最大 200）。
- **过滤**：通用查询参数 `keyword`, `status`, `org_id` 等，请参考相应端点。
- **国际化**：`lang`/`Accept-Language` 控制响应字段（如组织名称）。
- **错误格式**：

```json
{
  "error_code": "MEMBER_NOT_FOUND",
  "error_message": "成员不存在",
  "details": {
    "member_id": 123
  }
}
```

- **契约验证**：推荐在 CI 中执行 `python scripts/test_openapi_contract.py`，确保调用方实现符合最新契约。

---

## 6. 核心模块速查

| 模块 | 关键端点 | 典型用途 |
| --- | --- | --- |
| 成员 | `GET/POST /v2/members`, `GET /v2/members/{id}`, `POST /v2/members/{id}/roles`, `GET /v2/members/{id}/orgs` | 同步账号、分配角色、查询组织关系 |
| 角色 | `GET/POST /v2/roles`, `PUT /v2/roles/{id}`, `POST /v2/roles/{id}/permissions`, `POST /v2/roles/grant` | 角色生命周期、批量授权 |
| 权限 | `POST /v2/permissions/grant`, `/revoke`, `/check`, `/bitmap/*` | 直接授权、权限校验、位图缓存刷新 |
| 组织 | `GET /v2/orgs`, `/orgs/{id}`, `/orgs/{id}/hierarchy`, `/orgs/{id}/members` | 组织树、闭包查询、成员视图 |
| 资源 | `GET/POST /v2/resources` | 注册业务资源（微服务可自报资源维度） |
| 审计 | `GET /v2/audit/logs` | 查询操作轨迹、审批记录 |
| AI Agent | `GET/POST /v2/agents`, `/agents/{id}/credentials`, `/policy`, `/logs` | 管理虚拟成员及其凭证策略 |
| 系统设置 | `GET/PUT /v2/settings`, `/settings/{org_id}/{key}` | 环境/组织级配置（如特性开关） |
| 国际化 | `/v2/i18n/translations`, `/missing` | 自定义词条，供 UI/其他系统复用 |

---

## 7. 典型调用示例

### 7.1 成员同步（上游 HR → 成员系统）

1. **创建成员**

```bash
curl -X POST "$BASE_URL/v2/members" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: 1" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "zhangsan",
    "fullName": "张三",
    "email": "zhangsan@example.com",
    "status": "active",
    "isVirtual": false
  }'
```

2. **绑定组织与岗位**

```bash
curl -X POST "$BASE_URL/v2/members/{member_id}/orgs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: 1" \
  -d '{"org_id": 12, "title": "高级工程师", "is_primary": true}'
```

3. **授予角色**

```bash
curl -X POST "$BASE_URL/v2/members/{member_id}/roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: 1" \
  -d '{"role_ids": [101, 102], "expires_at": "2025-12-31T23:59:59Z"}'
```

### 7.2 权限即时校验（业务系统拦截器）

```bash
curl -X POST "$BASE_URL/v2/permissions/check" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: 1" \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": 9527,
    "resource_id": 3001,
    "required_mask": 6  // READ + WRITE
  }'
```

响应：

```json
{
  "allowed": true,
  "source": "role",
  "role_id": 102,
  "reason": "Role: order-manager (org=12)"
}
```

### 7.3 多语言组织树

```bash
curl "$BASE_URL/v2/orgs/12/hierarchy?lang=en" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: 1"
```

返回包含 `supportedLanguages`、`path`、`depth` 等字段，可映射到 `ORG_HIERARCHY_GUIDE.md` 提供的 SQL 存储过程。

### 7.4 审计查询

```bash
curl "$BASE_URL/v2/audit/logs?page=1&page_size=50&actor_id=9527" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: 1"
```

返回 MongoDB 中聚合的审计事件，字段包括 `tenant_id`, `category`, `action`, `resource`, `subject`, `payload_masked`, `occurred_at`。

### 7.5 AI Agent 凭证轮换

```bash
# 新建 Agent
curl -X POST "$BASE_URL/v2/agents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: 1" \
  -d '{"username":"bot.ops","fullName":"Ops Bot","agentType":"workflow","ownerMemberId":1001}'

# 生成凭证
curl -X POST "$BASE_URL/v2/agents/{agent_id}/credentials" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"type":"api_key","scope":["ticket.read","ticket.write"],"expires_at":"2025-03-01T00:00:00Z"}'
```

---

## 8. 异步与事件集成

### 8.1 Audit Outbox

1. **表结构**：`membership-repo/src/main/resources/db/migration/V9__Create_Audit_Outbox.sql`（字段含 `id`, `aggregate_type`, `aggregate_id`, `category`, `payload`, `occurred_at`, `processed` 等）。
2. **写入**：业务事务内同步写入 `audit_outbox`，保证与主交易一致。

### 8.2 CDC + Kafka

| 组件 | 配置参考 |
| --- | --- |
| Debezium Connector | `debezium-membership-connector.json`（`table.include.list=public.audit_outbox`，`slot.name=membership_audit_outbox_slot`） |
| Kafka Topic | `membership-server.public.audit_outbox`（见 `docs/V2.4_REMAINING_ALIGNMENT_PLAN.md`） |
| 消费服务 | `membership-audit` 模块，监听 Kafka，写入 MongoDB `events` 集合 |

> 若业务系统需实时订阅审计事件，可直接消费上述 Topic，或从 MongoDB `membership_audit.events` 查询。

### 8.3 回放与补偿

- **重放**：根据 `processed=false` 的 `audit_outbox` 记录重新投递。
- **Retention**：`audit.retention.cleanup` 任务（参考 `docs/V2.4_REMAINING_ALIGNMENT_PLAN.md`）支持 TTL 删除。
- **Fallback**：`audit.fallback_sync_write=true` 时可直接写 MongoDB，适用于 Kafka 故障场景。

---

## 9. 工具链、测试与验收

| 步骤 | 命令 / 文件 | 说明 |
| --- | --- | --- |
| 启动测试依赖 | `docker-compose -f docker-compose.test.yml up -d` | 启动 API + DB + Redis 等（README “快速开始”） |
| 健康检查 | `curl http://localhost:8080/actuator/health` | 验证服务启动 |
| Pytest 回归 | `python -m pytest tests/ -v` | 102/102 用例，覆盖成员、权限、审计等 |
| OpenAPI 契约 | `python scripts/test_openapi_contract.py` | 30 个端点，保障契约兼容 |
| 前端 E2E | Playwright specs (`membership-admin-ui/e2e-tests/*.spec.ts`) | 验证 UI 关键路径，与 API 场景一致 |
| 数据库脚本 | `init-database-v2.4-one-click.sh` | 初始化 schema + `audit_outbox` |

> 外部系统建议在联调前跑脚本验证接口一致性，再对接自身 Mock/集成测试。

---

## 10. 故障排查与支持

| 症状 | 可能原因 | 排查路径 |
| --- | --- | --- |
| 401/403 | Token 过期 / 缺失租户头 / 角色不足 | 检查 Token、`X-Tenant-ID`、`/v2/permissions/check` |
| 404 | 资源不在租户范围 | 确认 `tenant_id`、组织范围、RLS 配置 |
| 409 | 重复用户名/角色编码 | 使用 `/v2/members?keyword=` 或 `/v2/roles?code=` 预检 |
| 审计缺失 | `audit_outbox` 未处理或 Debezium 停止 | 查看 `membership-audit` 日志、Kafka Lag、`processed` 标记 |
| 位图不一致 | 本地缓存未刷新 | 调用 `/v2/permissions/bitmap/refresh` 或轮询 `/bitmap/{member_id}` |

### 支持渠道
- **文档**：`README.md`、`QUICK_START_GUIDE.md`、`TROUBLESHOOTING_GUIDE.md`
- **配置**：`application-*.yml`、`deploy/.env.example`
- **联系**：通过项目 Issue / 内部工单系统提交接入需求

---

## 11. 接入检查清单（建议）

1. ✅ 已创建租户与服务账户，保存 `client_id/client_secret`。
2. ✅ 已导入 `membership_openapi.yaml` 至 API 网关 / SDK。
3. ✅ 已完成登录 / Token 获取 / Refresh 测试。
4. ✅ 已验证成员 CRUD、角色授权与权限校验场景。
5. ✅ 已确认组织树、职位或 Agent 等扩展模型是否需要（如需提前对齐）。
6. ✅ （可选）已接入 Kafka 审计 Topic 或确认无需异步事件。
7. ✅ 在 CI/CD 中集成契约测试，确保版本升级可自动发现破坏性变更。

---

> 如需进一步的领域建模说明、ER 图和实施策略，请参考 `membership_management_full_design.md`、`docs/REST_API_IMPLEMENTATION_PLAN.md` 及阶段性报告。此手册将伴随 v2.4 发布持续更新。欢迎在 Issue 中提交改进建议。
