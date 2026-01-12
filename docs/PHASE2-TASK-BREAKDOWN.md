# Phase 2 任务分解详细计划

> 版本：2025-01-11
> 用途：详细的周度任务计划和依赖关系

---

## 📊 概览

```
Phase 2.1 (4周): 生成核心
├─ BPMN-MCP: 自然语言 → BPMN XML
├─ FORM-MCP: 自然语言 → 表单 JSON
├─ 前端编辑器: 可视化编辑和质量检查
└─ 集成接口: 与 Membership 对接

Phase 2.2 (4周): 运行时
├─ 知识库集成: MCP 查询政策
├─ WebApp 框架: 任务列表和表单
├─ 权限渲染: 字段级权限
└─ WebSocket: 实时推送

Phase 2.3 (4周): 优化和测试
├─ 性能优化: 缓存和异步
├─ 完整测试: 单元、集成、并发
├─ K8s 部署: 容器化和编排
└─ 文档完善: 用户和运维文档
```

---

## Phase 2.1: 生成核心 (周1-4)

### 周1: 详细设计和环境准备

#### 任务1.1: BPMN-MCP 详细设计 (3天)
- [ ] 分析 5 种执行者模式在 BPMN 中的表达方式
- [ ] 设计 BPMN-MCP 的输入 schema (自然语言 + 执行者配置)
- [ ] 设计 BPMN-MCP 的输出 schema (BPMN XML + metadata + confidence)
- [ ] 设计验证规则 (BPMN 合法性、执行者有效性、连接完整性)
- [ ] 设计错误处理 (无效的自然语言、引用不存在的角色等)
- **输出**: BPMN-MCP 技术设计文档 (PRD)

**依赖**:
- Membership 的角色/组织数据模型
- 5 种执行者模式的详细定义 (已在架构文档中)

---

#### 任务1.2: FORM-MCP 详细设计 (3天)
- [ ] 分析表单与 BPMN 任务的关系
- [ ] 设计字段权限的规则语言
- [ ] 设计字段与任务节点的绑定方式
- [ ] 设计表单 JSON 的完整 schema
- [ ] 设计字段级验证规则 (必填、类型、长度等)
- **输出**: FORM-MCP 技术设计文档 (PRD)

**依赖**:
- 表单设计的先前经验 (BPM 项目)
- BPMN-MCP 的设计 (理解任务上下文)

---

#### 任务1.3: 前端编辑器架构设计 (2天)
- [ ] 设计 ProcessEditor 的组件结构
- [ ] 设计 FormEditor 的组件结构
- [ ] 设计共享的验证组件
- [ ] 设计与 Membership API 的集成接口
- [ ] 设计错误提示和用户反馈机制
- **输出**: 前端架构设计文档 + 组件 API 定义

**依赖**:
- BPMN-MCP 和 FORM-MCP 的设计
- 共享组件库的标准

---

#### 任务1.4: 开发环境和测试数据准备 (2天)
- [ ] 搭建开发环境 (本地 Membership 实例或测试环境)
- [ ] 创建测试用的角色/组织数据
- [ ] 创建示例流程 (财务报销、采购、新药申报)
- [ ] 创建测试用例库
- [ ] 准备 mock 数据和测试脚本
- **输出**: 开发环境文档 + 测试数据

**依赖**:
- Membership 测试环境访问

---

### 周2: BPMN-MCP 和 FORM-MCP 开发

#### 任务2.1: BPMN-MCP 实现 (1周)
- [ ] 实现 LLM 提示词工程 (理解 5 种执行者模式)
- [ ] 实现 BPMN XML 生成逻辑
- [ ] 实现执行者配置验证 (调用 Membership API 检查角色是否存在)
- [ ] 实现 BPMN 逻辑验证 (连接完整性、无死循环等)
- [ ] 实现置信度评分
- [ ] 单元测试 (>80% 覆盖率)
- **输出**: BPMN-MCP 可运行代码 + 测试报告

**关键代码**:
```python
# 伪代码示例
class BpmnMcpTool:
    def generate_bpmn(self, requirement: str, executor_config: dict) -> dict:
        # 1. 调用 LLM 理解需求和执行者模式
        parsed = self.llm.parse_requirement(requirement)

        # 2. 验证执行者配置的真实性
        for executor in parsed.executors:
            if executor.type == "role":
                role = self.membership_client.get_role(executor.role_id)
                if not role:
                    raise ValueError(f"Role {executor.role_id} not found")

        # 3. 生成 BPMN XML
        bpmn_xml = self.bpmn_builder.build(parsed)

        # 4. 验证生成的 BPMN
        validation = self.bpmn_validator.validate(bpmn_xml)
        if not validation.is_valid:
            raise ValueError(f"BPMN validation failed: {validation.errors}")

        # 5. 返回结果
        return {
            "bpmn_xml": bpmn_xml,
            "executors": parsed.executors,
            "confidence": self.evaluate_confidence(requirement, bpmn_xml)
        }
```

**依赖**:
- Membership API 客户端 (角色/组织查询)
- BPMN 验证库 (XML 校验)

---

#### 任务2.2: FORM-MCP 实现 (1周)
- [ ] 实现 LLM 提示词工程 (理解表单需求和 BPMN 上下文)
- [ ] 实现字段生成逻辑
- [ ] 实现权限规则定义
- [ ] 实现字段验证规则
- [ ] 实现与 BPMN 任务的绑定
- [ ] 单元测试 (>80% 覆盖率)
- **输出**: FORM-MCP 可运行代码 + 测试报告

**依赖**:
- BPMN-MCP 的输出 (BPMN 上下文)
- 表单设计的先前经验

---

### 周3: 前端编辑器开发

#### 任务3.1: ProcessEditor 实现 (3天)
- [ ] 实现 BPMN 画布和节点拖拽
- [ ] 实现任务节点编辑 (名称、描述、执行者配置)
- [ ] 实现流向编辑
- [ ] 实现条件分支编辑
- [ ] 实现实时验证 (节点连接、执行者有效性等)
- [ ] 与 BPMN-MCP 集成 (可以把 AI 生成的 BPMN 导入编辑)
- **输出**: ProcessEditor 组件 + 集成示例

**关键功能**:
- 拖拽创建节点
- 拖拽创建连接
- 双击编辑节点属性
- 右键菜单 (删除、复制等)
- 撤销/重做
- 保存 JSON 表示

---

#### 任务3.2: FormEditor 实现 (3天)
- [ ] 实现字段选择板
- [ ] 实现表单画布和拖拽排列
- [ ] 实现字段属性编辑 (类型、验证规则、权限等)
- [ ] 实现权限规则编辑器 (可见性、可编辑性等)
- [ ] 实现字段与 BPMN 任务的绑定
- [ ] 实现字段级验证规则编辑
- **输出**: FormEditor 组件 + 集成示例

**关键功能**:
- 字段类型: 文本、数字、日期、选择、多选、文件等
- 权限配置: public | role:xxx | org:xxx
- 验证规则: 必填、长度、正则等
- 绑定配置: 哪些字段绑定到哪个任务

---

#### 任务3.3: 质量检查组件 (2天)
- [ ] 实现 BPMN 验证器
- [ ] 实现表单验证器
- [ ] 实现执行者配置验证
- [ ] 实现权限一致性检查
- [ ] 实现错误提示 UI
- **输出**: 验证组件库 + 集成示例

**验证规则**:
```
BPMN 验证:
  ✓ 至少有一个开始节点和结束节点
  ✓ 所有节点都有连接 (无孤立节点)
  ✓ 无死循环 (除了等待节点)
  ✓ 所有执行者引用存在

表单验证:
  ✓ 没有重复的字段 ID
  ✓ 权限规则有效 (引用的角色/组织存在)
  ✓ 必填字段的权限配置一致

执行者配置验证:
  ✓ 所有引用的角色存在
  ✓ 所有引用的组织存在
  ✓ 5 种执行者模式的配置正确
```

---

### 周4: 集成和测试

#### 任务4.1: 与 Membership 集成 (2天)
- [ ] 实现流程保存接口 (POST /v1/processes)
- [ ] 实现表单保存接口 (POST /v1/forms)
- [ ] 实现流程验证接口 (POST /v1/processes/{id}/validate)
- [ ] 实现版本管理逻辑
- **输出**: 集成接口实现 + API 文档

**API 设计**:
```
POST /v1/processes
├─ 请求: {bpmn_xml, name, description, form_id, version}
├─ 认证: service account
└─ 返回: {process_id, version, created_at}

POST /v1/forms
├─ 请求: {form_json, name, description, version}
└─ 返回: {form_id, version, created_at}

POST /v1/processes/{id}/validate
├─ 请求: {bpmn_xml}
└─ 返回: {valid, errors[], warnings[]}
```

**依赖**:
- Membership API 客户端
- BPM 的数据模型设计

---

#### 任务4.2: 端到端测试 (2天)
- [ ] 测试 BPMN-MCP 生成 → 编辑 → 保存的完整流程
- [ ] 测试 FORM-MCP 生成 → 编辑 → 保存的完整流程
- [ ] 测试多种流程类型 (线性、分支、并行、循环等)
- [ ] 测试执行者验证 (无效的角色、组织等)
- [ ] 性能测试 (生成速度、编辑响应时间等)
- [ ] 测试报告和问题修复
- **输出**: 测试报告 + 已验证的流程示例

**测试用例**:
```
✓ 简单线性流程 (3 个任务)
✓ 带分支的流程 (条件路由)
✓ 并行任务流程
✓ 循环流程
✓ 混合流程 (所有元素)
✓ 错误处理 (无效输入、角色不存在等)
```

**依赖**:
- 所有之前的任务完成
- Membership 测试环境

---

#### 任务4.3: 文档编写 (1天)
- [ ] BPMN-MCP 使用文档
- [ ] FORM-MCP 使用文档
- [ ] 前端编辑器用户指南
- [ ] 集成接口文档
- [ ] 常见问题解答
- **输出**: 完整的用户文档

---

## Phase 2.2: 运行时 (周5-8)

### 周5: 知识库集成和 WebApp 基础

#### 任务5.1: 知识库 API 集成 (3天)
- [ ] 调研 Membership 知识库 API 的实现
- [ ] 实现 MCP 知识库客户端
  - [ ] 全文搜索接口
  - [ ] 语义搜索接口 (向量搜索)
  - [ ] 分类查询接口
- [ ] 实现缓存机制 (Redis)
- [ ] 实现超时和重试逻辑
- [ ] 单元测试
- **输出**: 知识库集成代码

**代码示例**:
```python
class KnowledgeBaseClient:
    def __init__(self, membership_url, cache_client):
        self.membership_url = membership_url
        self.cache = cache_client

    def search(self, query: str, limit: int = 10) -> List[Document]:
        # 检查缓存
        cache_key = f"kb:search:{query}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # 查询知识库
        results = requests.post(
            f"{self.membership_url}/v1/knowledge-base/search",
            json={"query": query, "limit": limit}
        ).json()

        # 保存缓存 (1小时)
        self.cache.setex(cache_key, 3600, results)
        return results
```

**依赖**:
- Membership 知识库 API 的实现和文档

---

#### 任务5.2: WebApp 基础框架 (2天)
- [ ] 设计 WebApp 的整体架构 (页面、路由等)
- [ ] 实现登录页 (已有, 确认集成)
- [ ] 实现首页 (导航、常用流程卡片等)
- [ ] 实现任务列表页
  - [ ] 显示待办任务
  - [ ] 搜索和过滤
  - [ ] 分页
- [ ] 集成 Axios API 客户端
- [ ] 集成 Membership 认证
- **输出**: WebApp 基础框架代码

**页面结构**:
```
WebApp/
├─ pages/
│  ├─ LoginPage
│  ├─ HomePage (常用流程卡片 + 待办列表)
│  ├─ TaskListPage (完整任务列表)
│  ├─ TaskDetailPage (单个任务详情)
│  ├─ ProcessHistoryPage (已提交的流程)
│  └─ ProfilePage (个人设置)
├─ components/
│  ├─ TaskCard
│  ├─ FormRenderer (根据 form_schema 渲染)
│  ├─ ProcessViewer (显示流程图)
│  └─ ...
└─ services/
   ├─ api.ts (Membership API 客户端)
   ├─ websocket.ts (WebSocket 连接)
   └─ auth.ts (认证管理)
```

**依赖**:
- React 开发环境
- API 接口文档

---

### 周6: 表单权限和任务管理

#### 任务6.1: 表单权限渲染 (3天)
- [ ] 实现 FormRenderer 组件 (根据 form_schema 渲染)
- [ ] 实现权限过滤逻辑
  - [ ] 隐藏无权限字段
  - [ ] 只读权限字段
  - [ ] 必填字段标记
- [ ] 实现字段验证显示
- [ ] 实现表单提交逻辑
- [ ] 单元测试和集成测试
- **输出**: FormRenderer 组件 + 集成示例

**代码逻辑**:
```typescript
// FormRenderer.tsx
interface FormRendererProps {
  formSchema: FormSchema;
  formData: Record<string, any>;
  userPermissions: string[];
  onSubmit: (data: Record<string, any>) => void;
}

export const FormRenderer: React.FC<FormRendererProps> = ({
  formSchema,
  formData,
  userPermissions,
  onSubmit
}) => {
  return (
    <div>
      {formSchema.fields.map(field => {
        // 检查用户权限
        const canView = checkPermission(field.visibility, userPermissions);
        if (!canView) return null; // 隐藏

        const canEdit = checkPermission(field.editability, userPermissions);
        const isRequired = checkPermission(field.required, userPermissions);

        return (
          <FormField
            key={field.id}
            field={field}
            value={formData[field.id]}
            readOnly={!canEdit}
            required={isRequired}
            onChange={(value) => { /* ... */ }}
          />
        );
      })}
      <button onClick={() => onSubmit(formData)}>提交</button>
    </div>
  );
};
```

**依赖**:
- FORM-MCP 的输出 (form_schema)
- Membership 权限系统

---

#### 任务6.2: 任务管理功能 (2天)
- [ ] 实现任务列表显示 (前 10 条)
- [ ] 实现任务搜索和过滤
- [ ] 实现任务详情页
- [ ] 实现表单提交逻辑 (POST 到后端)
- [ ] 实现任务认领逻辑 (角色队列模式)
- [ ] 错误处理和提示
- **输出**: 任务管理页面和逻辑

**关键功能**:
```
任务列表:
  ├─ 显示待办任务 (任务名、截止日期、优先级)
  ├─ 显示"认领"按钮 (如果是队列任务)
  ├─ 显示"打开"按钮
  └─ 搜索和过滤 (按名称、状态等)

任务详情:
  ├─ 显示流程图 (当前步骤高亮)
  ├─ 显示表单 (权限过滤后)
  ├─ 显示历史记录 (时间线)
  └─ 操作按钮 ([同意]/[不同意]/[保存草稿]/[提交])

任务提交:
  ├─ 验证表单数据
  ├─ 调用后端 POST /v1/workflows/{id}/submit
  ├─ 显示成功/失败消息
  └─ 刷新任务列表
```

**依赖**:
- 后端 API 实现
- FormRenderer 组件

---

### 周7-8: WebSocket 和流程启动

#### 任务7.1: WebSocket 实时推送 (2天)
- [ ] 实现 WebSocket 连接 (ws://membership/ws)
- [ ] 实现心跳 (keep-alive)
- [ ] 实现断线重连机制
- [ ] 实现事件监听
  - [ ] task.assigned (新任务)
  - [ ] task.claimed (任务被认领)
  - [ ] process.updated (流程进度)
  - [ ] notification.* (系统通知)
- [ ] 集成到 WebApp (显示通知、刷新任务列表等)
- **输出**: WebSocket 客户端 + 集成示例

**代码框架**:
```typescript
// websocket.ts
export class WebSocketClient {
  private ws: WebSocket;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  connect(url: string, token: string) {
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };

    this.ws.onclose = () => {
      this.reconnect(url, token);
    };
  }

  private handleMessage(message: any) {
    switch (message.event) {
      case 'task.assigned':
        // 新任务, 显示通知
        console.log('New task assigned:', message.data);
        // 刷新任务列表
        break;
      case 'task.claimed':
        // 其他人认领了任务
        console.log('Task claimed:', message.data);
        break;
      // ...
    }
  }

  private reconnect(url: string, token: string) {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      setTimeout(() => {
        this.connect(url, token);
      }, 1000 * this.reconnectAttempts); // 指数退避
    }
  }
}
```

**依赖**:
- Membership WebSocket 端点的实现

---

#### 任务7.2: 流程启动功能 (2天)
- [ ] 实现"可用流程"页面
  - [ ] 根据用户角色/组织显示可用流程
  - [ ] 显示流程描述和统计信息
  - [ ] 可定制的卡片 UI (配置常用流程)
- [ ] 实现"启动流程"功能
  - [ ] 选择流程 → 显示初始表单 → 提交
  - [ ] 集成 FormRenderer
- [ ] 实现流程启动的验证和错误处理
- **输出**: 流程启动页面

**UI 设计**:
```
首页:
  ├─ 【常用流程】卡片区
  │  ├─ 报销申请 [卡片]
  │  ├─ 采购申请 [卡片]
  │  └─ 请假申请 [卡片]
  │
  ├─ 【所有流程】搜索和列表
  │  ├─ 搜索框
  │  ├─ 分类筛选
  │  └─ 流程列表
  │
  └─ 【我的流程】
     ├─ 待办数 (X项)
     ├─ 已完成数 (Y项)
     └─ 进行中 (Z项)
```

**依赖**:
- Membership API (流程列表、权限检查)
- FormRenderer 组件

---

#### 任务7.3: 整体测试和文档 (2天)
- [ ] 端到端测试 (启动流程 → 填表 → 提交 → 任务显示)
- [ ] WebSocket 推送测试
- [ ] 权限测试 (不同角色看到不同流程和字段)
- [ ] 性能测试
- [ ] 文档编写 (WebApp 用户指南)
- **输出**: 测试报告 + 用户文档

---

## Phase 2.3: 优化和测试 (周9-12)

### 周9: 性能优化

#### 任务9.1: 缓存优化 (2天)
- [ ] 实现流程定义缓存 (Redis)
- [ ] 实现表单定义缓存
- [ ] 实现知识库查询缓存 (已有 + 优化)
- [ ] 实现任务列表缓存策略
- [ ] 性能测试和基准线设置
- **输出**: 缓存实现 + 性能报告

---

#### 任务9.2: 异步优化 (2天)
- [ ] 审计日志异步写入 (Kafka)
- [ ] 长时间操作的后台处理
- [ ] MCP 查询的异步化 (如需要)
- [ ] 性能测试
- **输出**: 异步优化代码

---

#### 任务9.3: 其他优化 (1天)
- [ ] 代码优化 (减少重复查询、数据库索引等)
- [ ] 前端包大小优化 (tree shaking、代码分割等)
- [ ] 性能监控设置 (Prometheus 指标等)
- **输出**: 优化报告

---

### 周10: 完整测试

#### 任务10.1: 单元测试 (1天)
- [ ] BPMN-MCP 单元测试 (已有 + 补充)
- [ ] FORM-MCP 单元测试 (已有 + 补充)
- [ ] 前端组件单元测试
- [ ] 目标: 覆盖率 > 80%
- **输出**: 测试报告

---

#### 任务10.2: 集成测试 (2天)
- [ ] 端到端流程测试 (生成 → 编辑 → 保存 → 执行 → 完成)
- [ ] 权限测试 (不同角色的访问控制)
- [ ] 多流程并发测试
- [ ] 错误恢复测试
- **输出**: 测试用例库 + 报告

---

#### 任务10.3: 并发和负载测试 (2天)
- [ ] 并发认领测试 (10-100 人同时认领同一任务)
- [ ] 大流程性能测试 (100+ 节点的流程)
- [ ] 知识库查询性能测试
- [ ] 系统容量测试 (最大并发实例数)
- [ ] 生成性能基准线 (单个 Docker 支持多少并发)
- **输出**: 性能基准线 + 容量报告

---

#### 任务10.4: 安全和合规测试 (1天)
- [ ] 多租户隔离测试 (租户 A 无法访问租户 B 的数据)
- [ ] SQL 注入防护测试
- [ ] CSRF 防护测试
- [ ] 敏感数据脱敏测试
- [ ] 审计日志完整性测试
- **输出**: 安全测试报告

---

### 周11: K8s 部署

#### 任务11.1: 容器化 (2天)
- [ ] 为 AICMDEngine 编写 Dockerfile
- [ ] 为 WebApp 编写 Dockerfile
- [ ] 本地测试容器镜像
- [ ] 构建和推送镜像到仓库
- **输出**: 可用的容器镜像

---

#### 任务11.2: K8s 编排 (2天)
- [ ] 编写 K8s Deployment 配置 (AICMDEngine)
- [ ] 编写 K8s Deployment 配置 (WebApp)
- [ ] 编写 K8s Service 配置 (暴露 API)
- [ ] 编写 Ingress 配置 (路由)
- [ ] 编写 ConfigMap 和 Secret 配置 (配置管理)
- [ ] 设置 HPA (水平自动伸缩)
- **输出**: 完整的 K8s 部署配置

**示例配置**:
```yaml
# aicmdengine-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aicmdengine
spec:
  replicas: 2
  selector:
    matchLabels:
      app: aicmdengine
  template:
    metadata:
      labels:
        app: aicmdengine
    spec:
      containers:
      - name: aicmdengine
        image: aicmdengine:latest
        ports:
        - containerPort: 8000
        env:
        - name: MEMBERSHIP_URL
          valueFrom:
            configMapKeyRef:
              name: aicmdengine-config
              key: membership_url
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: aicmdengine-service
spec:
  selector:
    app: aicmdengine
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

---

#### 任务11.3: 部署测试 (1天)
- [ ] 在 K8s 开发集群部署
- [ ] 功能测试 (流程生成、保存、执行等)
- [ ] 伸缩测试 (增加副本数, 验证流量分散)
- [ ] 故障转移测试 (kill pod, 验证自动重启)
- **输出**: 部署指南 + 验收报告

---

### 周12: 文档和上线准备

#### 任务12.1: 文档编写 (2天)
- [ ] 系统架构文档 (最终版)
- [ ] API 文档 (完整的 OpenAPI/Swagger)
- [ ] 部署运维指南
- [ ] 故障排查指南
- [ ] 用户手册 (乙方 + 甲方)
- [ ] MCP 开发指南 (如何开发新的 MCP)
- **输出**: 完整的文档库

---

#### 任务12.2: 上线准备 (1天)
- [ ] 生产环境检查清单
- [ ] 安全审计清单
- [ ] 性能基准线验收
- [ ] 数据迁移计划 (如有测试数据)
- [ ] 回滚计划
- [ ] 监控告警配置
- **输出**: 上线准备文档

---

#### 任务12.3: 培训和交接 (1天)
- [ ] 乙方内部培训 (如何维护系统)
- [ ] 甲方用户培训 (如何使用)
- [ ] 甲方管理员培训 (如何配置流程、知识库等)
- [ ] 常见问题解答
- **输出**: 培训材料 + 录制视频

---

## 依赖关系图

```
Phase 2.1:
  ├─ 周1: 详细设计 (并行进行)
  │  ├─ 任务1.1: BPMN-MCP 设计
  │  ├─ 任务1.2: FORM-MCP 设计
  │  ├─ 任务1.3: 前端架构设计
  │  └─ 任务1.4: 环境准备
  │
  ├─ 周2-3: 开发 (依赖周1)
  │  ├─ 任务2.1: BPMN-MCP 实现
  │  ├─ 任务2.2: FORM-MCP 实现
  │  ├─ 任务3.1: ProcessEditor
  │  ├─ 任务3.2: FormEditor
  │  └─ 任务3.3: 质量检查
  │
  └─ 周4: 集成和测试 (依赖周2-3)
     ├─ 任务4.1: Membership 集成
     ├─ 任务4.2: 端到端测试
     └─ 任务4.3: 文档

Phase 2.2:
  ├─ 周5: 知识库 + WebApp 基础 (依赖 Phase 2.1)
  │  ├─ 任务5.1: 知识库集成
  │  └─ 任务5.2: WebApp 框架
  │
  ├─ 周6-8: WebApp 功能 (依赖周5)
  │  ├─ 任务6.1: 表单权限
  │  ├─ 任务6.2: 任务管理
  │  ├─ 任务7.1: WebSocket
  │  └─ 任务7.2: 流程启动
  │
  └─ 周8: 整体测试 (依赖周6-7)
     └─ 任务7.3: E2E 测试

Phase 2.3:
  ├─ 周9: 性能优化 (依赖 Phase 2.2)
  ├─ 周10: 完整测试 (依赖周9)
  ├─ 周11: K8s 部署 (可并行周9-10)
  └─ 周12: 文档和上线 (依赖周9-11)
```

---

## 资源估算

### 人力分配建议

```
BPMN-MCP 实现 (2人, 4周):
  ├─ 1人: LLM 提示工程 + 验证逻辑
  └─ 1人: 代码实现 + 测试

FORM-MCP 实现 (2人, 4周):
  ├─ 1人: LLM 提示工程 + 权限规则
  └─ 1人: 代码实现 + 测试

前端编辑器 (2人, 4周):
  ├─ 1人: ProcessEditor + FormEditor
  └─ 1人: 验证逻辑 + UI 调优

WebApp 实现 (2人, 4周):
  ├─ 1人: 后端集成 + API 调用
  └─ 1人: UI 实现 + 权限渲染

测试和运维 (2人, 全程):
  ├─ 1人: 测试设计和执行
  └─ 1人: 部署 + K8s + 监控

项目管理 (1人, 全程):
  └─ 1人: 协调、文档、沟通

总计: 11 人 (可根据实际调整)
```

---

## 里程碑和检查点

```
Week 4:  Phase 2.1 完成
  ├─ [ ] BPMN-MCP 可用
  ├─ [ ] FORM-MCP 可用
  ├─ [ ] 前端编辑器可用
  └─ [ ] 能够生成和保存流程/表单

Week 8:  Phase 2.2 完成
  ├─ [ ] WebApp 可用
  ├─ [ ] 知识库集成完成
  ├─ [ ] WebSocket 推送工作
  └─ [ ] 能够启动流程并提交任务

Week 12: Phase 2.3 完成 (上线就绪)
  ├─ [ ] 所有测试通过
  ├─ [ ] K8s 部署配置完成
  ├─ [ ] 性能基准线达到目标
  └─ [ ] 文档完整, 可上线
```

---

## 风险和缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| Membership API 延迟交付 | 中 | 提前协调, 备选方案 |
| MCP 生成质量不达预期 | 中 | 迭代优化提示词, 收集反馈 |
| 性能达不到目标 | 中 | 提前性能测试, K8s 伸缩 |
| 多租户隔离有问题 | 低 | 严格的安全审计 |

---

完成这 12 周的工作,即可完成 Phase 2!🚀
