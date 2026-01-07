# Phase 1.3 核心业务功能集成计划

## 当前状态
- ✅ Phase 1.1（基础设施）已完成
- ✅ Phase 1.2（认证系统）已完成
- 🔄 Phase 1.3（核心业务功能）正在规划

## Phase 1.3 的复杂性分析

### 已存在的组件（需要集成 API）
```
plan2/src/components/
  ├─ ChatPanel.tsx（任务规划交互）
  └─ PlannerExecutorPanel.tsx（执行面板）
```

### 需要集成的后台 API
根据 NL-TPS 设计文档，需要调用的 API 端点：

**核心 API 调用**：
1. `GET /command-sets` - 获取命令集列表
2. `POST /tasks` - 提交任务目标，获取 AI 规划
3. `POST /tasks/{taskId}/steps/{stepId}/execute` - 执行单个步骤
4. `GET /tasks/{taskId}` - 获取任务详情和执行状态

## Phase 1.3.1：Chat Panel 集成

### 需要实现的功能
```typescript
interface ChatPanelProps {
  commandSetId: string;
}

// 功能：
1. 显示历史对话
2. 接收用户自然语言输入
3. 调用 POST /tasks 获取规划
4. 显示 AI 返回的规划
5. 将规划结果同步到 Planner & Executor Panel
```

### 实现步骤

**1.1 更新数据结构**
```typescript
interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface TaskPlan {
  taskId: string;
  steps: Step[];
  status: string;
}

interface Step {
  stepId: number;
  command: string;
  parameters: Record<string, any>;
  description?: string;
}
```

**1.2 添加 API 调用**
```typescript
const handlePlanTask = async (goal: string) => {
  try {
    const response = await api.post('/tasks', {
      commandSetId,
      goal,
      context: {}
    });

    // 返回示例：
    // { taskId, steps, plan: [...] }

    return response.data;
  } catch (error) {
    // 错误处理
  }
}
```

**1.3 更新 UI 显示**
- 将中文示例数据替换为真实 API 数据
- 添加加载状态和错误处理
- 实现自动滚动到最新消息
- 添加发送按钮的事件处理

**1.4 翻译文本为英文**
- 所有消息文本
- 所有标签
- 所有提示文本

---

## Phase 1.3.2：Planner & Executor Panel 集成

### 需要实现的功能
```typescript
interface PlannerExecutorPanelProps {
  commandSetId: string;
  taskPlan?: TaskPlan;  // 从 Chat Panel 接收
}

// 功能：
1. 接收来自 Chat Panel 的规划
2. 显示每个步骤（只读）
3. 允许执行单步或全部执行
4. 显示执行状态和结果
5. 显示执行日志
```

### 实现步骤

**2.1 接收规划结果**
```typescript
// 从 Chat Panel 接收 taskPlan
// 存储在状态中或通过 Context 传递
```

**2.2 显示规划步骤**
- 遍历 taskPlan.steps
- 显示命令、参数、依赖关系
- 显示状态指示器

**2.3 实现执行逻辑**
```typescript
const executeStep = async (stepId: number) => {
  try {
    const response = await api.post(
      `/tasks/${taskId}/steps/${stepId}/execute`,
      { parameters: step.parameters }
    );

    // 返回示例：
    // { status: 'success', result: {...}, duration: 245 }

    return response.data;
  } catch (error) {
    // 错误处理
  }
}

const executeAll = async () => {
  // 顺序执行所有步骤
  for (const step of steps) {
    await executeStep(step.stepId);
  }
}
```

**2.4 显示执行结果**
- 实时更新步骤状态
- 显示执行日志
- 显示命令输出
- 错误情况下显示详细信息

**2.5 翻译文本为英文**
- 所有标签
- 所有按钮文本
- 所有提示信息

---

## Phase 1.3.3：Dashboard 业务逻辑

### 需要实现的功能
- 动态加载命令集列表
- 在 Chat 和 Planner 之间传递数据
- 管理任务状态

### 实现步骤

**3.1 加载命令集列表**
```typescript
const loadCommandSets = async () => {
  try {
    const response = await api.get('/command-sets');
    setCommandSets(response.data);
  } catch (error) {
    // 错误处理
  }
}
```

**3.2 建立数据流**
```
Dashboard
  ├─ Chat Panel（用户输入 → 规划）
  │   └─ 规划结果传递到 Planner
  └─ Planner & Executor Panel（执行规划）
```

**3.3 翻译文本为英文**
- 命令集名称
- 所有 UI 标签

---

## Phase 1.3.4：创建 Command Sets 管理页面

### 需要实现的功能（暂定为简化版）
- 显示命令集列表
- 基本的导入/删除功能（可选）

### 实现步骤
1. 创建 CommandSets.tsx 页面
2. 调用 `GET /command-sets` 获取列表
3. 显示列表和基本操作
4. 翻译为英文

---

## 关键挑战和注意事项

### 1. API 响应格式
**需要确认的问题**：
- `POST /tasks` 的确切响应格式是什么？
- 步骤执行的响应格式？
- 错误响应的格式？

### 2. 数据流管理
**方案 1：通过 Props 传递**（当前 Dashboard 结构）
- Chat Panel 调用 API，得到规划
- 将规划传递给 Planner Panel
- 简单但可能需要状态提升

**方案 2：使用 Context（推荐）**
```typescript
// 创建 TaskContext
// 在 Dashboard 中提供
// Chat 和 Planner 共享状态
```

**方案 3：URL 状态**
- 将规划放在 URL 参数中
- 刷新页面时保持状态

**推荐**：方案 2（Context） - 最清晰和可维护

### 3. 错误处理
- API 超时
- 网络错误
- 后台返回的错误
- Token 过期（需要重定向登录）

### 4. 加载状态
- API 调用时显示加载指示器
- 防止重复点击

### 5. 后台可能的限制
- 需要了解执行的时间限制
- 是否支持实时进度反馈（WebSocket）或轮询？
- 最大任务步骤数？
- 最大参数大小？

---

## 实施顺序

### 推荐顺序
1. ✅ **确认后台 API 规范** - 必须先做
   - 确切的请求/响应格式
   - 错误处理方式
   - 超时和重试策略

2. 🔄 **实现 Context 状态管理** - 数据流基础
   - 创建 TaskContext
   - 在 Dashboard 中提供

3. 🔄 **集成 Chat Panel API**
   - 加载命令集列表
   - 实现任务规划 API 调用
   - 更新 UI 和翻译文本

4. 🔄 **集成 Planner & Executor API**
   - 显示规划结果
   - 实现执行逻辑
   - 更新 UI 和翻译文本

5. 🔄 **Command Sets 管理页面**（可选或简化版）
   - 显示列表
   - 基本操作

6. ✅ **全面测试**
   - 完整的任务流程测试
   - 错误处理测试
   - 边界情况测试

---

## 时间估算

- 确认 API 规范：**必须**（阻塞其他工作）
- Context 实现：2-3 小时
- Chat Panel 集成：3-4 小时
- Planner & Executor 集成：4-5 小时
- Command Sets 页面：2-3 小时
- 测试和调试：3-4 小时
- **总计：14-19 小时**

---

## 下一步

1. **立即需要**：获取后台 API 的完整规范
   - 请求和响应的 JSON Schema
   - 错误处理方式
   - 超时和性能考虑

2. **准备好后开始实施**：按上述顺序逐步实现

3. **每个子步骤完成后**：
   - 构建并测试
   - 提交代码
   - 更新 todo 列表

