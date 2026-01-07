# Plan2 UI 功能规范

## 页面布局概览

```
┌─────────────────────────────────────────────────────────────┐
│                        PLAN2 DASHBOARD                       │
├──────────┬──────────────────────────────────────────────────┤
│          │  顶部：Command Set 选择和管理                      │
│  左侧    ├──────────────────────────────────────────────────┤
│  菜单    │                                                   │
│  栏      │  中部：两个并排面板                              │
│          │  ┌────────────────┬────────────────┐             │
│  - Task  │  │                │                │             │
│    Playground  │    CHAT      │  Planner &    │             │
│    (任务规划)  │   Panel      │   Executor    │             │
│  - Command   │  (输入、规划)  │   Panel       │             │
│    Sets    │                │  (审核、执行)  │             │
│  - Settings│                │                │             │
│  - Analytics│   ────────────┼────────────    │             │
│  - Docs    │   (消息历史)    │   (结果显示)    │             │
│            │                │                │             │
│            └────────────────┴────────────────┘             │
│            │                                               │
│            │  底部：输入框（仅在 Task Playground）         │
│            │                                               │
└────────────┴───────────────────────────────────────────────┘
```

---

## 核心理解：两个工作面板的分工

### Chat Panel（左侧）- 任务规划交互
**职责**：用户与 AI 交互，规划任务

**功能流程**：
```
1. 用户输入自然语言描述
   "给 R&D 部门新增一个员工 Zhang San"

2. 点击 "Plan" 按钮
   ↓ 调用 POST /v1/tasks
   ↓ 参数：{ commandSetId, goal, context }

3. 显示 AI 规划结果
   ↓ 返回结构化的任务计划
   ↓ 包含：steps, commands, parameters

4. 显示规划对话历史
   ↓ 可以继续修改或重新规划
```

**UI 组件**：
- 上部：任务规划历史对话（消息流）
- 下部：
  - 输入框：`Describe your task goal...`
  - "Plan" 按钮：触发 AI 规划

**数据示例**：
```json
用户输入：
"Add a new employee named Zhang San to the R&D department"

规划结果（AI 返回）：
{
  "taskId": "task-001",
  "steps": [
    {
      "stepId": 1,
      "command": "create_employee",
      "parameters": {
        "name": "Zhang San",
        "department": "R&D"
      }
    }
  ]
}
```

---

### Planner & Executor Panel（右侧）- 审核和执行
**职责**：显示和执行规划好的任务命令/接口调用序列

**功能流程**：
```
1. 从 Chat Panel 接收规划结果
   ↓ 显示任务计划（步骤列表）

2. 用户审核每个步骤
   ↓ 查看命令名称
   ↓ 查看参数
   ↓ 确认无误后执行

3. 执行任务
   ↓ 逐步执行计划中的每个命令/API 调用
   ↓ 显示每步的执行状态（运行中/成功/失败）

4. 显示执行结果
   ↓ 命令执行的输出
   ↓ 返回的数据
   ↓ 任何错误信息
```

**UI 组件**：
- 上部：任务规划展示（只读）
  - 步骤号
  - 命令名称
  - 参数列表
  - 状态指示（待执行/执行中/成功/失败）

- 下部：执行控制
  - "Execute" 按钮：执行所有步骤
  - "Execute Step" 按钮：逐步执行
  - "Reset" 按钮：重置执行状态
  - "Copy Plan" 按钮：复制规划为 JSON

- 最下部：结果显示
  - 执行日志
  - 命令输出
  - 错误堆栈（如有）

**数据示例**：
```json
显示的规划步骤：
[
  {
    "stepId": 1,
    "status": "pending",  // pending | running | success | failure
    "command": "POST /members/create",
    "parameters": {
      "name": "Zhang San",
      "department": "R&D",
      "position": "Engineer"
    }
  },
  {
    "stepId": 2,
    "status": "pending",
    "command": "POST /departments/assign",
    "parameters": {
      "memberId": "${step1.result.id}",
      "departmentId": "dept-001"
    }
  }
]

执行结果：
{
  "stepId": 1,
  "status": "success",
  "output": {
    "id": "member-123",
    "name": "Zhang San",
    "department": "R&D"
  },
  "duration": "245ms"
}
```

---

## 交互流程图

### 完整的任务规划-执行流程

```
┌─────────────────────────────────────────────────────────┐
│ 1. 用户选择 Command Set（顶部下拉菜单）                  │
└──────────────────────┬──────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────┐
│ 2. 用户在 Chat Panel 输入任务描述                        │
│    "Add new employee Zhang San to R&D"                  │
└──────────────────────┬──────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────┐
│ 3. 点击 "Plan" 按钮                                      │
│    → 调用 POST /v1/tasks                               │
│    → 参数：{ commandSetId, goal, context }             │
└──────────────────────┬──────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────┐
│ 4. AI 生成规划，返回结构化步骤                           │
│    Planner & Executor Panel 显示规划                    │
│                                                         │
│    ✓ Step 1: create_employee                           │
│      Parameters: { name, department, ... }             │
│                                                         │
│    ✓ Step 2: assign_to_department                      │
│      Parameters: { memberId, departmentId, ... }       │
└──────────────────────┬──────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────┐
│ 5. 用户在 Planner & Executor 审核规划                   │
│    确认参数、命令顺序等                                 │
└──────────────────────┬──────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────┐
│ 6. 点击 "Execute" 按钮开始执行                          │
│    → 逐步调用后台接口执行每个步骤                       │
│    → 显示执行进度和状态                                 │
└──────────────────────┬──────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────┐
│ 7. 显示执行结果                                          │
│    - 成功：显示返回的数据                                │
│    - 失败：显示错误消息和日志                            │
│    - 继续选项：重新规划、修改参数、重新执行             │
└─────────────────────────────────────────────────────────┘
```

---

## Chat Panel 详细规范

### 上部：规划历史（消息流）

**展示内容**：
- 用户消息：蓝色气泡
  ```
  User: "Add new employee Zhang San to R&D"
  ```

- AI 响应：绿色气泡
  ```
  AI: I've planned 2 steps:
  Step 1: create_employee with params {name, department}
  Step 2: assign_to_department with params {memberId, departmentId}
  ```

- 自动同步到 Planner & Executor Panel

**滚动**：
- 自动滚动到最新消息
- 支持上拉加载历史

---

### 下部：输入和控制区

**布局**：
```
┌─────────────────────────────────────────────────┐
│ Describe your task goal...                      │
│ __________________________|                     │
│ [Plan] [Clear] [Settings]                      │
└─────────────────────────────────────────────────┘
```

**组件**：
- **输入框**：
  - Placeholder：`"Describe your task goal..."`
  - 支持多行输入
  - 按 Shift+Enter 换行，Enter 提交
  - 或点击 Plan 按钮提交

- **Plan 按钮**：
  - 触发 POST /v1/tasks
  - 显示加载状态（转菊花）
  - 禁用状态：未选择 Command Set、输入框为空

- **Clear 按钮**：清空输入框

- **Settings 按钮**：
  - 可选，用于高级设置
  - 如：上下文、模型选择等

---

## Planner & Executor Panel 详细规范

### 上部：任务规划展示（只读）

**每个步骤的展示**：
```
┌──────────────────────────────────────────────┐
│ Step 1  |  Status: ⏳ Pending                 │
├──────────────────────────────────────────────┤
│ Command:  create_employee                   │
│                                              │
│ Parameters:                                 │
│   • name: "Zhang San"                       │
│   • department: "R&D"                       │
│   • position: "Engineer"                    │
│                                              │
│ Dependencies: None                          │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│ Step 2  |  Status: ⏳ Pending                 │
├──────────────────────────────────────────────┤
│ Command:  assign_to_department              │
│                                              │
│ Parameters:                                 │
│   • memberId: ${step1.result.id}           │
│   • departmentId: "dept-001"                │
│                                              │
│ Dependencies: Requires Step 1 success       │
└──────────────────────────────────────────────┘
```

**状态指示**：
- ⏳ Pending（灰色）- 等待执行
- ⚙️ Running（蓝色旋转）- 执行中
- ✓ Success（绿色）- 成功
- ✗ Failed（红色）- 失败

**样式**：
- 卡片式布局
- 默认展开（可收起）
- 复制按钮：快速复制参数 JSON

---

### 下部：执行控制区

**布局**：
```
┌─────────────────────────────────────────────┐
│ [Execute All] [Step By Step] [Reset]        │
├─────────────────────────────────────────────┤
│ Execution Logs:                             │
│                                             │
│ [19:45:23] Step 1 started...                │
│ [19:45:24] Step 1 completed (245ms)         │
│ [19:45:25] Step 2 started...                │
│ [19:45:26] Step 2 completed (312ms)         │
│                                             │
│ Total Duration: 557ms                       │
│ Status: ✓ All steps completed successfully  │
└─────────────────────────────────────────────┘
```

**执行按钮**：
- **Execute All**：一键执行所有步骤（顺序执行）
  - 显示进度条
  - 若某步失败，停止执行并显示错误

- **Step By Step**：逐步执行
  - 显示"下一步"按钮
  - 用户点击后执行当前步骤
  - 显示单步结果后再执行下一步

- **Reset**：重置状态
  - 清空日志
  - 将所有步骤状态设为 Pending
  - 关闭执行结果

---

### 最下部：执行结果显示

**成功结果**：
```
✓ Step 1 Result:
{
  "id": "member-123",
  "name": "Zhang San",
  "department": "R&D",
  "createdAt": "2025-01-07T19:45:24Z"
}
Duration: 245ms
```

**失败结果**：
```
✗ Step 2 Failed:
Error: Department not found

Details:
  Code: DEPARTMENT_NOT_FOUND
  Message: The specified department (dept-999) does not exist

Stack:
  at assignToDepartment (backend/services/...)
  at executeStep (backend/api/...)
```

**结果区功能**：
- 代码高亮（JSON 格式）
- 复制按钮
- 折叠/展开
- 清空日志按钮

---

## 顶部：Command Set 选择和管理

### Command Set 选择区

**布局**：
```
┌──────────────────────────────────────────────┐
│ 🛠️ Command Set:  [Membership API v2.4 ▼]    │
│ 📝 Description: User and department...       │
│ Version: 2.4.1  |  Type: OpenAPI            │
├──────────────────────────────────────────────┤
│ [Import] [Refresh] [Manage]                 │
└──────────────────────────────────────────────┘
```

**功能**：
- **下拉菜单**：选择已导入的命令集（调用 GET /command-sets）
- **描述显示**：显示选中命令集的描述
- **元数据显示**：版本、类型等
- **Import 按钮**：导入新命令集（打开导入对话框）
- **Refresh 按钮**：刷新命令集列表
- **Manage 按钮**：跳转到 Command Sets 管理页面

---

## 菜单项说明

### Task Playground（当前活跃菜单）
**展示**：上述的完整布局（Chat + Planner & Executor）

### Command Sets
**展示**：
- 命令集列表（表格）
- 列：Name、Description、Version、Type、Actions
- Actions：Edit、Delete、Export、View Details
- 按钮：Import New、Refresh

### Settings
**展示**：
- API 配置（仅管理员）
- 用户偏好
- 主题设置

### Analytics
**显示**：
- 任务执行统计
- 历史任务列表
- 执行趋势图

### Documentation
**显示**：
- 使用指南
- API 文档链接
- 常见问题

---

## 数据流总结

```
用户输入
    ↓
Chat Panel: 用户发送任务描述
    ↓
    → 调用 POST /v1/tasks
    ↓
Planner & Executor Panel: 显示规划结果
    ↓
用户审核规划
    ↓
用户点击 Execute
    ↓
    → 逐步调用后台接口执行每个步骤
    → POST /tasks/{taskId}/steps/{stepId}/execute
    ↓
显示每步执行结果
    ↓
任务完成或失败
    ↓
用户可以：
  • 查看历史（Analytics）
  • 重新规划
  • 导出执行记录
```

---

## 关键 API 调用

| 操作 | API 端点 | 触发位置 |
|------|---------|---------|
| 获取命令集列表 | GET /command-sets | 顶部下拉菜单加载 |
| 规划任务 | POST /v1/tasks | Chat Panel 点击 Plan |
| 执行步骤 | POST /v1/tasks/{taskId}/steps/{stepId}/execute | Planner & Executor 点击 Execute |
| 获取任务状态 | GET /v1/tasks/{taskId} | 执行过程中轮询（可选） |

---

## 设计原则

1. **关注点分离明确**
   - Chat：规划交互
   - Planner & Executor：审核和执行
   - 两个面板无需直接交互，通过后台数据联动

2. **用户体验**
   - 清晰的步骤展示
   - 实时反馈执行状态
   - 错误时显示详细信息
   - 支持重试和回滚（由后台决定）

3. **前后端分离**
   - 前端：展示、交互、数据绑定
   - 后台：规划、执行、数据存储
   - 前端完全依赖后台数据

