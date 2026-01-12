# Phase 2 启动文档

> 版本：2025-01-11
> 状态：启动
> 核心目标：实现 AI 驱动的流程/表单生成与执行引擎

---

## 一、Phase 2 的目标

### 核心成果物

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 2 交付物                                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ 1. BPMN-MCP (流程生成)                                      │
│    ├─ 输入: 自然语言需求 + 企业执行者配置 (真实角色)       │
│    ├─ 输出: BPMN 2.0 XML (已验证, 可执行)                 │
│    └─ 核心能力: 支持 5 种执行者模式                        │
│                                                             │
│ 2. FORM-MCP (表单生成)                                      │
│    ├─ 输入: 自然语言需求 + BPMN 上下文                     │
│    ├─ 输出: 表单 JSON 定义 (字段 + 权限 + 验证)           │
│    └─ 核心能力: 字段级权限, 动态可见性                     │
│                                                             │
│ 3. 前端编辑器                                              │
│    ├─ ProcessEditor (BPMN 可视化编辑)                     │
│    ├─ FormEditor (表单可视化编辑)                         │
│    ├─ 质量检查 (实时验证)                                  │
│    └─ 共享渲染组件 (与 WebApp 复用)                       │
│                                                             │
│ 4. 与 Membership 的集成接口                                │
│    ├─ 流程/表单保存 API                                    │
│    ├─ 知识库查询 API                                       │
│    ├─ 执行者配置验证                                       │
│    └─ 权限和角色查询                                       │
│                                                             │
│ 5. WebApp 基础框架                                          │
│    ├─ 待办任务列表显示                                     │
│    ├─ 表单权限渲染                                         │
│    ├─ WebSocket 实时推送 (基础)                           │
│    └─ 流程启动入口 (可用流程列表)                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、Phase 2 的三个子阶段

### Phase 2.1 (周1-4): 流程/表单生成核心

**目标**：完成 BPMN-MCP 和 FORM-MCP 的基础版本

```yaml
Phase 2.1 交付物:

  BPMN-MCP:
    ├─ 支持 5 种执行者模式的识别和配置
    ├─ 自动验证执行者配置 (角色是否存在)
    ├─ 生成可执行的 BPMN 2.0 XML
    ├─ 支持条件分支和并行任务
    └─ 生成置信度评分

  FORM-MCP:
    ├─ 基于 BPMN 上下文生成表单
    ├─ 支持字段级权限定义
    ├─ 生成完整的 JSON 表单定义
    └─ 字段与任务的绑定

  前端编辑器:
    ├─ ProcessEditor 基础功能
    ├─ FormEditor 基础功能
    ├─ 前端实时验证 (必填、类型等)
    └─ 保存按钮 → 调用 Membership API

  集成接口:
    ├─ POST /v1/processes (保存流程)
    ├─ POST /v1/forms (保存表单)
    ├─ GET /v1/members?role=xxx (查询角色成员)
    └─ POST /v1/processes/{id}/validate (验证流程)
```

**关键决策**：
- ✅ 参考 BPM 项目的 `DATA_MODEL_DESIGN` 来设计存储结构
- ✅ 执行者配置必须验证真实的 Membership 角色
- ✅ 生成的 BPMN XML 在保存前必须验证

**success criteria**:
- [ ] BPMN-MCP 能生成可被 Flowable 执行的 BPMN XML
- [ ] FORM-MCP 能生成包含权限的完整表单定义
- [ ] 前端编辑器能保存流程/表单到 Membership
- [ ] 执行者配置验证能检出不存在的角色

---

### Phase 2.2 (周5-8): 运行时执行基础

**目标**：完成 WebApp 和知识库集成的基础

```yaml
Phase 2.2 交付物:

  知识库集成:
    ├─ POST /v1/knowledge-base/search (全文搜索)
    ├─ POST /v1/knowledge-base/semantic-search (向量搜索)
    ├─ GET /v1/knowledge-base/policy?category=xxx (分类查询)
    └─ 超时控制和结果限制

  MCP 知识库调用:
    ├─ MCP 能调用知识库查询 API
    ├─ 支持缓存优化
    └─ 错误重试机制

  WebApp 框架:
    ├─ 任务列表显示 (前 10 条)
    ├─ 表单权限渲染
    │  ├─ 隐藏无权限字段
    │  ├─ 只读权限字段
    │  └─ 必填字段标记
    ├─ 表单提交到后端
    └─ 流程启动 (选择流程 → 填表 → 提交)

  WebSocket 实时推送:
    ├─ ws://membership/ws (基础连接)
    ├─ 新任务推送 (task.assigned)
    ├─ 任务认领推送 (task.claimed)
    └─ 断线重连机制
```

**关键决策**：
- ✅ 知识库查询 API 由 Membership 提供
- ✅ WebApp 流程启动采用"选项 A + 可定制卡片"
- ✅ 表单权限完全基于 Membership 的访问控制
- ✅ WebSocket 用于实时任务推送

**success criteria**:
- [ ] MCP 能成功查询知识库并获取政策文档
- [ ] WebApp 能显示用户的待办任务列表
- [ ] 表单根据用户权限正确显示/隐藏字段
- [ ] 用户能启动新流程并填表提交

---

### Phase 2.3 (周9-12): 优化和完善

**目标**：性能优化、测试、部署准备

```yaml
Phase 2.3 交付物:

  性能优化:
    ├─ 流程定义缓存 (Redis)
    ├─ 知识库查询缓存
    ├─ 任务列表分页优化
    └─ 审计日志异步写入

  测试:
    ├─ 单元测试 (BPMN-MCP, FORM-MCP)
    ├─ 集成测试 (端到端流程)
    ├─ 并发测试 (同时认领同一任务)
    ├─ 权限测试 (字段级权限)
    └─ 负载测试 (大流程, 大任务量)

  文档完善:
    ├─ BPMN-MCP 开发指南
    ├─ FORM-MCP 开发指南
    ├─ 知识库查询 API 文档
    ├─ WebApp 部署指南
    └─ 故障排查指南

  K8s 部署:
    ├─ Dockerfile (AICMDEngine, WebApp)
    ├─ K8s manifest 文件
    ├─ 水平伸缩配置
    └─ 监控和告警
```

**关键决策**：
- ✅ 使用 K8s 解决并发问题
- ✅ 多租户隔离测试放在这个阶段
- ✅ 性能指标: 单个 Docker 支持多少并发 (需要测试)

**success criteria**:
- [ ] 系统能支持 100+ 并发流程实例
- [ ] 知识库查询 P99 < 500ms
- [ ] 单 Docker 能处理 XXX 个任务/秒
- [ ] 所有测试通过, 覆盖率 > 80%

---

## 三、技术栈确认

### 后端 (已有, Membership)

```
├─ 语言: Java (Membership)
├─ 流程引擎: Flowable 6.7.0
├─ 数据库: PostgreSQL 16
├─ 知识库: MongoDB + ES + Milvus
├─ 缓存: Redis 7
├─ 消息队列: Kafka 3.8
├─ 审计: Debezium CDC
└─ 部署: K8s + Docker
```

### 前端 (AICMDEngine + WebApp)

```
├─ 框架: React 18+
├─ BPMN 编辑: bpmn-js (Diagram.js)
├─ 表单编辑: 自定义编辑器
├─ 网络: Axios (HTTP) + ws (WebSocket)
├─ 状态管理: Zustand / Context
├─ UI 库: 自定义或 Ant Design
└─ 部署: Nginx + K8s
```

### MCP

```
├─ 语言: Python
├─ 框架: Claude Agent SDK
├─ 调用方式: HTTP + REST API
└─ 知识库客户端: requests + Milvus SDK
```

---

## 四、依赖和前置条件

### ✅ 已准备好

- Membership 后端系统 (执行引擎)
- BPM 项目的存储设计 (`DATA_MODEL_DESIGN`)
- 共享的 React 组件库骨架
- 测试数据和测试租户

### ⏳ 需要准备

- [ ] Membership 提供知识库查询 API 端点
- [ ] Membership 提供流程/表单保存 API 端点
- [ ] Membership 提供成员/角色查询 API (已有)
- [ ] Membership WebSocket 端点
- [ ] 开发环境的 K8s 集群 (可选, 测试时用)
- [ ] 开发测试数据 (示例流程、测试用户、示例政策)

---

## 五、关键设计决策（摘自架构审视）

### 1️⃣ 存储设计 (问题1)
- **方案**: 参考 BPM 的 DATA_MODEL_DESIGN
- **存储位置**: MongoDB (Membership 内)
- **关键字段**: version, created_at, updated_by, tenant_id

### 2️⃣ 执行者验证 (问题8)
- **方案**: 设计时检查真实的 Membership 角色/组织
- **实现**: BPMN-MCP 生成后自动验证 + 前端拖拽时验证

### 3️⃣ 性能解决 (问题6)
- **方案**: K8s 水平伸缩
- **TODO**: 测试单个 Docker 的并发能力

### 4️⃣ 表单权限 (问题7)
- **方案**: 基于 Membership 的访问控制 (RLS)
- **实现**: 后端过滤 + 前端隐藏

### 5️⃣ 流程启动 (问题9)
- **方案**: 选项 A (用户选择流程) + 可定制卡片
- **权限**: 根据用户角色/组织显示可用流程

### 6️⃣ 甲方修改 (问题11)
- **方案**: 通过法律条款保护
- **实现**: 如允许修改需要特别约定

### 7️⃣ 多租户隔离 (问题12)
- **方案**: 放到 Phase 2.3 测试
- **TODO**: 上线前必须完成验证

---

## 六、工作分配建议

### 后端 / Membership 工作

- [ ] 实现知识库查询 API (4周)
  - 全文搜索 (ElasticSearch)
  - 向量搜索 (Milvus)
  - 分类和过滤

- [ ] 实现流程/表单保存 API (2周)
  - 参考 BPM DATA_MODEL_DESIGN
  - 版本管理
  - 验证逻辑

- [ ] WebSocket 实时推送 (2周)
  - 任务推送
  - 进度更新
  - 断线重连

### 前端 / AICMDEngine 工作

- [ ] BPMN-MCP 开发 (4周)
  - 5 种执行者模式识别
  - BPMN XML 生成
  - 执行者验证

- [ ] FORM-MCP 开发 (4周)
  - 基于 BPMN 上下文
  - 字段级权限
  - JSON 生成

- [ ] 前端编辑器 (4周)
  - ProcessEditor 实现
  - FormEditor 实现
  - 质量检查

- [ ] WebApp 基础框架 (3周)
  - 任务列表
  - 表单渲染
  - 权限过滤

### DevOps / 测试工作

- [ ] K8s 部署配置 (2周)
- [ ] 集成测试框架 (2周)
- [ ] 并发/性能测试 (2周)
- [ ] 安全审计 (1周)

---

## 七、风险和缓解策略

### 🔴 高风险

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|--------|
| MCP 生成的 BPMN 有逻辑错误 | 中 | 高 | 自动化验证 + 用户反馈 |
| 知识库查询超时 | 中 | 中 | 缓存 + 异步查询 |
| 多租户数据泄露 | 低 | 极高 | Phase 2.3 严格测试 |
| 性能达不到要求 | 中 | 中 | K8s 伸缩 + 缓存优化 |

### 🟡 中风险

| 风险 | 缓解策略 |
|------|--------|
| Membership API 有问题 | 提前联系, 备选方案 |
| 前端组件重复开发 | 制定共享组件标准 |
| 测试覆盖不足 | 提前规划测试用例 |

---

## 八、成功标准

### 🎯 Phase 2.1 成功

```
✅ BPMN-MCP 能生成可被 Flowable 执行的 BPMN XML
✅ FORM-MCP 能生成包含权限的表单定义
✅ 前端编辑器能保存流程/表单到 Membership
✅ 执行者验证能检出不存在的角色
✅ 生成的流程可以在 Membership 中启动执行
```

### 🎯 Phase 2.2 成功

```
✅ WebApp 能显示用户的待办任务
✅ 表单权限正确渲染 (隐藏/只读/编辑)
✅ 用户能启动新流程
✅ WebSocket 能实时推送新任务
✅ 知识库查询 API 正常工作
```

### 🎯 Phase 2.3 成功

```
✅ 所有单元测试通过 (覆盖率 > 80%)
✅ 集成测试通过 (端到端流程)
✅ 并发测试通过 (100+ 并发实例)
✅ 性能指标达到目标
✅ K8s 部署配置完成
✅ 多租户隔离验证通过
```

---

## 九、时间表

```
Week 1-4  (Jan 13 - Feb 9):     Phase 2.1 核心实现
  ├─ Week 1-2: BPMN-MCP + FORM-MCP 设计和开发
  ├─ Week 2-3: 前端编辑器开发
  └─ Week 4: 集成和测试

Week 5-8  (Feb 10 - Mar 9):     Phase 2.2 运行时
  ├─ Week 5: 知识库 API 集成
  ├─ Week 6: WebApp 框架
  ├─ Week 7-8: WebSocket + 权限渲染
  └─ Week 8: 集成和测试

Week 9-12 (Mar 10 - Apr 6):     Phase 2.3 优化
  ├─ Week 9: 性能优化
  ├─ Week 10: 全量测试
  ├─ Week 11: K8s 部署
  └─ Week 12: 文档和上线准备

总计: 12 周
```

---

## 十、交付物清单

### Phase 2.1 交付物
- [ ] BPMN-MCP 代码 + 文档
- [ ] FORM-MCP 代码 + 文档
- [ ] ProcessEditor 组件
- [ ] FormEditor 组件
- [ ] 集成接口文档
- [ ] 测试用例和测试报告

### Phase 2.2 交付物
- [ ] WebApp 框架代码
- [ ] 知识库集成代码
- [ ] WebSocket 实现
- [ ] 权限渲染逻辑
- [ ] 用户手册

### Phase 2.3 交付物
- [ ] 性能优化报告
- [ ] 完整的测试报告
- [ ] K8s 部署配置
- [ ] 部署和运维指南
- [ ] 最终用户文档

---

## 十一、下一步行动

### 🔴 立即行动 (本周)

1. [ ] 与 Membership 团队确认知识库 API 的实现计划
2. [ ] 与 Membership 团队确认流程/表单保存 API 的实现计划
3. [ ] 查看 BPM 项目的 `DATA_MODEL_DESIGN` 文档
4. [ ] 准备开发环境和测试数据
5. [ ] 制定前端共享组件的标准

### 🟡 下周行动

1. [ ] 启动 BPMN-MCP 和 FORM-MCP 的详细设计
2. [ ] 启动前端编辑器的架构设计
3. [ ] 启动集成测试框架的搭建

---

## 总结

**Phase 2 是 AICMDEngine 从架构设计到实现的关键阶段。**

这 12 周的工作将完成：
- ✅ AI 驱动的流程/表单生成 (BPMN-MCP + FORM-MCP)
- ✅ 企业级的流程执行和管理 (与 Membership 集成)
- ✅ 员工日常的工作平台 (WebApp)

**架构已验证，风险已识别，条件已准备。**

现在可以全力推进! 🚀
