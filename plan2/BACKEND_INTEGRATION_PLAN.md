# Plan2 后台集成计划（修正版）

## 目标
将 plan2 前端应用与 NL-TPS（Natural Language Task Planning Service）后台集成，实现三个核心业务功能，使用英文界面。

---

## 应用定位

Plan2 是 NL-TPS 的前端客户端，主要职责是：
1. **管理命令集/API 接口集** - Command Sets Management
2. **规划和执行任务** - Task Planning & Execution
3. **查看执行历史** - Task History & Monitoring

---

## 现状分析

### 后台服务架构（NL-TPS）
根据 `docs/NL_TASK_PLANNING_SERVICE_DESIGN_EN.md`：

**核心概念**：
- **Command Sets**：存储 OpenAPI 规范或自定义命令集
- **Commands**：原子命令定义（从 Command Set 派生）
- **Tasks**：用户的自然语言目标请求
- **Plans**：AI 生成的结构化执行计划

**主要 API 端点**：
- `POST /v1/tasks` - 提交任务，获取规划
- `GET/POST /v1/command-sets` - 管理命令集
- `GET/POST /v1/commands` - 查询命令
- `GET /v1/tasks/{taskId}` - 查看任务状态

### Plan2 当前状态
- **端口**：3000（需改为 5122）
- **界面语言**：中文（需改为英文）
- **缺少的内容**：
  - Login 界面（认证）
  - Command Sets 管理界面的后台集成
  - Task Planning 的后台 API 调用
  - Task Execution 的后台交互
  - 所有 API 调用和数据绑定

---

## 核心业务流程

### 流程 1：Command Sets Management（命令集管理）
```
用户 → 导航到 "Command Sets"
     → 查看命令集列表（调用 GET /v1/command-sets）
     → 导入/创建新命令集（调用 POST /v1/command-sets）
     → 编辑或删除（调用 PUT/DELETE /v1/command-sets/{id}）
```

### 流程 2：Task Planning & Execution（任务规划和执行）
```
用户 → 导航到 "Task Playground"
     → 选择命令集（下拉选择，从列表中获取）
     → 输入自然语言任务目标
     → 点击 "Plan"（调用 POST /v1/tasks，获取规划）
     → 显示 AI 生成的任务计划（步骤、参数等）
     → 点击 "Execute"（逐步执行计划中的命令，调用后台接口）
     → 显示执行结果和历史
```

### 流程 3：Task History（任务历史）
```
用户 → 导航到 "Analytics" 或专门的历史页面
     → 查看已完成任务列表（调用 GET /v1/tasks）
     → 点击任务查看详细执行日志
```

---

## 任务分解

### 阶段 1：基础设施准备

#### 任务 1.1：修改端口和安装依赖
**文件修改**：
- `plan2/vite.config.ts` - 端口改为 5122
- `plan2/package.json` - 添加 axios 依赖

**实现内容**：
```typescript
// vite.config.ts
server: {
  port: 5122,
}

// package.json - dependencies
"axios": "^1.4.0"
```

---

#### 任务 1.2：创建配置和 API 客户端系统
**文件创建/修改**：
- `plan2/src/config.ts` - 配置加载系统
- `plan2/src/lib/api.ts` - Axios API 客户端和拦截器
- `plan2/public/config.json` - 运行时配置
- `plan2/src/main.tsx` - 初始化时加载配置

**功能要求**：
- 动态配置 API 端点（`nlTpsApiUrl`，默认 `http://localhost:8000/v1`）
- 两个 Axios 实例：
  - `api`：业务 API 调用
  - `membershipApi`：认证相关（仅用于登录）
- 请求拦截器自动添加：
  - `Authorization: Bearer {token}`
  - `X-Tenant-ID: {tenantId}`

---

### 阶段 2：认证和入口

#### 任务 2.1：创建 Login 界面
**文件创建**：
- `plan2/src/pages/Login.tsx` - 登录页面

**功能要求**：
- 用户名/邮箱和密码输入
- 登录按钮
- 调用后台认证接口（Membership API）
- 成功后保存 token 和 tenantId 到 localStorage
- 重定向到 Dashboard

**参考**：`ui/src/pages/Login.tsx`（如有的话）

---

#### 任务 2.2：实现路由和认证状态管理
**文件修改**：
- `plan2/src/App.tsx` - 添加路由，实现登录重定向
- `plan2/src/pages/Dashboard.tsx` - 添加登出功能

**功能要求**：
- 检查 localStorage 中的 token，未登录则重定向到 Login
- Dashboard 顶部或侧边栏显示登出按钮
- 点击登出清空 token 和 tenantId

---

### 阶段 3：核心业务功能

#### 任务 3.1：Command Sets 管理界面集成
**文件修改**：
- `plan2/src/pages/Dashboard.tsx` - "Command Sets" 菜单项逻辑

**功能要求**：
- 显示命令集列表（调用 `GET /v1/command-sets`）
- 显示字段：name、description、version、sourceType
- 添加"导入"或"创建"按钮（调用 `POST /v1/command-sets`）
- 支持删除操作（调用 `DELETE /v1/command-sets/{id}`）
- 实时刷新列表

**示例 API 调用**：
```typescript
const response = await api.get('/command-sets');
// 响应包含：{ data: [{ id, name, description, version, ... }] }
```

---

#### 任务 3.2：Task Playground - 任务规划
**文件修改**：
- `plan2/src/components/ChatPanel.tsx` - 任务输入和规划
- `plan2/src/pages/Dashboard.tsx` - 命令集选择

**功能要求**：
- 顶部：下拉菜单选择命令集（从列表中获取）
- 中部左侧 (CHAT Panel)：
  - 文本框输入自然语言任务描述
  - "Plan" 按钮 → 调用 `POST /v1/tasks`
  - 显示返回的任务计划（步骤、参数等）

**示例 API 调用**：
```typescript
const response = await api.post('/tasks', {
  commandSetId: selectedCommandSetId,
  goal: userInput,
  context: {}
});
// 响应包含：{ data: { taskId, steps, plan: [...] } }
```

---

#### 任务 3.3：Task Playground - 任务执行
**文件修改**：
- `plan2/src/components/PlannerExecutorPanel.tsx` - 执行界面

**功能要求**：
- 显示规划中的各个步骤
- 每个步骤可以独立执行或自动顺序执行
- 调用后台接口执行每个步骤
- 显示执行结果、日志、错误信息
- 实时更新执行状态

**示例 API 调用**：
```typescript
// 执行单个步骤
const response = await api.post(`/tasks/${taskId}/steps/${stepId}/execute`, {
  parameters: stepParams
});
// 响应包含：{ status: 'success/failure', result, logs, ... }
```

---

#### 任务 3.4：Task History（可选但推荐）
**文件创建**：
- `plan2/src/pages/TaskHistory.tsx` - 任务历史页面

**功能要求**：
- 显示已完成或运行中的任务列表
- 调用 `GET /v1/tasks` 获取列表
- 点击任务查看详细信息和执行日志
- 支持搜索、过滤、排序

---

### 阶段 4：界面和文本本地化

#### 任务 4.1：将所有界面转换为英文
**涉及文件**：
- `plan2/src/pages/Dashboard.tsx`
- `plan2/src/components/ChatPanel.tsx`
- `plan2/src/components/PlannerExecutorPanel.tsx`
- `plan2/src/pages/Login.tsx`（新建）

**具体修改**：
| 中文 | 英文 |
|------|------|
| MENU | Menu |
| Task Playground | Task Playground |
| Command Sets | Command Sets |
| Settings | Settings |
| Analytics | Analytics |
| Documentation | Documentation |
| User | User |
| Logout | Logout |
| 输入您的消息 | Enter your task description... |
| AI在线 | AI Online |
| CHAT | Chat |
| Planner & Executor | Planner & Executor |
| 命令集 | Command Set |
| 选择要执行的命令集 | Select a command set to execute |
| 导入 | Import |
| 刷新 | Refresh |

---

## 实现策略

### 方案：基于 UI 已验证的方案 + 任务驱动

**优点**：
- 代码一致性高
- 已验证的架构模式
- 易于维护和扩展

**核心原则**：
1. **参照 UI 实现** - 复用认证、配置、API 调用的模式
2. **按业务流程实现** - 优先实现登录 → Command Sets → Task Planning → Execution
3. **增量交付** - 每个子任务独立可测，可逐步集成
4. **英文优先** - 从一开始就使用英文 labels

---

## 依赖关系和执行顺序

```
阶段 1（基础设施）
├─ 1.1 端口改为 5122，安装 axios
└─ 1.2 创建配置和 API 客户端系统
        ↓
阶段 2（认证）
├─ 2.1 创建 Login 界面
└─ 2.2 实现路由和认证状态管理
        ↓
阶段 3（业务功能）
├─ 3.1 Command Sets 管理
├─ 3.2 Task Planning（规划）
├─ 3.3 Task Execution（执行）
└─ 3.4 Task History（可选）
        ↓
阶段 4（本地化）
└─ 4.1 转换所有界面为英文
```

**并行可行**：
- 1.1 和 1.2 的规划可以同时进行
- 2.1 和 2.2 的规划可以同时进行
- 3.1、3.2、3.3 的规划可以同时进行

---

## 后台 API 集成要点

### 必要的 API 端点（根据 NL-TPS 设计）

| 功能 | 方法 | 端点 | 说明 |
|------|------|------|------|
| 获取命令集列表 | GET | `/command-sets` | 列出当前租户的所有命令集 |
| 创建命令集 | POST | `/command-sets` | 导入或创建新命令集 |
| 删除命令集 | DELETE | `/command-sets/{id}` | 删除指定命令集 |
| 提交任务规划 | POST | `/tasks` | 提交任务目标，获取 AI 规划 |
| 获取任务详情 | GET | `/tasks/{id}` | 获取任务和执行状态 |
| 执行计划步骤 | POST | `/tasks/{id}/steps/{stepId}/execute` | 执行计划中的单个步骤 |
| 获取任务列表 | GET | `/tasks` | 获取已完成或运行中的任务 |

### 错误处理

**常见状态码**：
- `200` - 成功
- `401` - 未认证（重定向到 Login）
- `403` - 无权限
- `404` - 资源不存在
- `422` - 验证失败（显示错误消息）
- `500` - 服务器错误

**建议**：
- 所有 API 调用使用 try-catch
- 显示用户友好的错误提示
- 记录完整的错误堆栈用于调试

---

## 前后端分工明确

### 前端（Plan2）职责
- ✅ 接收用户输入
- ✅ 调用后台 API
- ✅ 显示规划和执行结果
- ✅ 管理 UI 状态和交互

### 后台（NL-TPS）职责
- ✅ 生成任务规划（AI）
- ✅ 管理命令集
- ✅ 验证和执行命令
- ✅ 持久化数据

**关键点**：前端不执行命令，只显示和协调；所有执行逻辑都由后台完成。

---

## 验证策略

### 开发阶段
1. ✅ 端口 5122 启动正常
2. ✅ config.json 加载成功
3. ✅ 登录功能可用
4. ✅ Command Sets 列表可查询
5. ✅ 任务规划 API 能调用

### 集成测试
1. ✅ 完整登录流程
2. ✅ 导入命令集和查看列表
3. ✅ 提交任务并获取规划
4. ✅ 执行任务并显示结果
5. ✅ 查看任务历史

### 端到端测试
1. ✅ 用户完整使用流程（登录 → 选择集 → 规划 → 执行）
2. ✅ 错误处理和恢复
3. ✅ 性能和可靠性

---

## 时间规划（相对复杂度）

| 任务 | 复杂度 |
|------|--------|
| 1.1 端口和依赖 | ⭐ 非常简单 |
| 1.2 配置和 API 客户端 | ⭐⭐ 简单 |
| 2.1 Login 界面 | ⭐⭐ 简单 |
| 2.2 路由和认证状态 | ⭐⭐ 简单 |
| 3.1 Command Sets 管理 | ⭐⭐⭐ 中等 |
| 3.2 Task Planning | ⭐⭐⭐ 中等 |
| 3.3 Task Execution | ⭐⭐⭐⭐ 中等-偏复杂 |
| 3.4 Task History | ⭐⭐⭐ 中等 |
| 4.1 英文本地化 | ⭐ 简单 |

---

## 风险和缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 后台 API 文档不完整 | 高 | 与后台团队确认端点和响应格式 |
| 认证 token 过期 | 中 | 实现 token 刷新或重定向登录 |
| CORS 限制 | 中 | 确保后台配置 CORS 头 |
| 网络不稳定 | 中 | 添加重试机制和超时处理 |
| 后台 API 不可用 | 低 | 提供 Mock API 用于开发 |

---

## 下一步

1. ✅ **确认此计划** - 验证架构和任务分解是否符合需求
2. ⏳ **获得后台 API 文档** - 确保了解所有端点的请求/响应格式
3. ⏳ **按阶段实施** - 从阶段 1 开始，逐步推进
4. ⏳ **每个子任务后测试** - 确保集成正确
5. ⏳ **交付前端到端测试** - 完整业务流程验证

---

## 附录

### 后台服务地址配置

**开发环境** (`plan2/public/config.json`):
```json
{
  "nlTpsApiUrl": "http://localhost:8000/v1",
  "membershipApiUrl": "http://localhost:8001/v1"
}
```

### 示例文档参考
- `docs/NL_TASK_PLANNING_SERVICE_DESIGN_EN.md` - 后台架构
- `docs/NATURAL_LANGUAGE_COMMAND_FRAMEWORK.md` - 命令框架
- `ui/src/lib/api.ts` - API 客户端实现参考
- `ui/src/config.ts` - 配置系统参考

