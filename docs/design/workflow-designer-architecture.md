# Workflow Designer Architecture Design

**Version**: 1.0.0
**Date**: 2026-01-14
**Status**: Design Phase

## 1. Overview

Workflow Designer 是一个集成了 AI 协作能力的工作流设计工具，支持：
- BPMN 2.0 流程设计 (ProcessEditor)
- 动态表单设计 (FormEditor)
- 流程与表单绑定管理 (Bindings)
- AI 辅助生成与编辑 (Chat Panel)
- Membership 组织架构集成

## 2. Layout Design

### 2.1 整体布局

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Header                                                                 │
│  Workflow Designer: [流程名称]                      [Preview] [Save]    │
├─────────────────────────────────────────────────────────────────────────┤
│  Tab Bar                                                                │
│  [Process ▼]  [Form]  [Bindings]                            [⚙️ Props] │
├─────────────────────────────────────────────┬───────────────────────────┤
│                                             │                           │
│                                             │  AI Chat Panel            │
│                                             │  (可收起)                 │
│         Main Canvas Area                    │                           │
│         根据 Tab 切换:                       │  ┌─────────────────────┐ │
│         - ProcessEditor (BPMN)              │  │ 对话历史...          │ │
│         - FormEditor (Form)                 │  │                     │ │
│         - BindingsView (关系图)              │  │ [输入框...]         │ │
│                                             │  └─────────────────────┘ │
│                                             │                           │
├─────────────────────────────────────────────┴───────────────────────────┤
│  Validation Bar                                                         │
│  ✓ 2 warnings  |  Last saved: 10:30                                    │
└─────────────────────────────────────────────────────────────────────────┘

Properties Panel: 点击 [⚙️] 或双击元素时从右侧滑出
Membership Selector: 在需要选择角色/部门/成员时弹出对话框
```

### 2.2 响应式设计

| 屏幕宽度 | 布局调整 |
|---------|---------|
| > 1440px | Chat Panel 固定显示，Properties 滑出 |
| 1024-1440px | Chat Panel 可收起，Properties 滑出 |
| < 1024px | Chat Panel 变为底部抽屉，Properties 全屏模态框 |

## 3. Component Architecture

### 3.1 组件树

```
WorkflowDesigner/
├── WorkflowDesignerPage.tsx      # 主页面容器
├── components/
│   ├── Header/
│   │   ├── WorkflowHeader.tsx    # 顶部工具栏
│   │   └── WorkflowTabs.tsx      # Tab 切换
│   │
│   ├── Canvas/
│   │   ├── ProcessEditor/        # BPMN 流程编辑器
│   │   │   ├── ProcessEditor.tsx
│   │   │   ├── BpmnCanvas.tsx    # bpmn-js 封装
│   │   │   ├── ElementPalette.tsx # 元素工具箱
│   │   │   └── ExecutorConfigEditor.tsx
│   │   │
│   │   ├── FormEditor/           # 表单编辑器
│   │   │   ├── FormEditor.tsx
│   │   │   ├── FormCanvas.tsx    # 表单画布
│   │   │   ├── ControlPalette.tsx # 控件工具箱 (37种)
│   │   │   ├── ControlRenderer.tsx # 控件渲染器
│   │   │   └── PermissionRuleEditor.tsx
│   │   │
│   │   └── BindingsView/         # 绑定关系视图
│   │       ├── BindingsView.tsx
│   │       └── BindingCard.tsx
│   │
│   ├── Panels/
│   │   ├── ChatPanel/            # AI 聊天面板
│   │   │   ├── ChatPanel.tsx
│   │   │   ├── ChatMessage.tsx
│   │   │   ├── ChatInput.tsx
│   │   │   └── PreviewActions.tsx # 应用/修改/重新生成
│   │   │
│   │   ├── PropertiesPanel/      # 属性编辑面板 (滑出式)
│   │   │   ├── PropertiesPanel.tsx
│   │   │   ├── ProcessProperties.tsx  # 流程节点属性
│   │   │   ├── FormFieldProperties.tsx # 表单字段属性
│   │   │   └── BindingProperties.tsx   # 绑定属性
│   │   │
│   │   └── ValidationPanel/      # 验证结果
│   │       └── ValidationBar.tsx
│   │
│   └── Modals/                   # 弹出式对话框
│       ├── MembershipSelector/   # 组织架构选择器
│       │   ├── MembershipSelectorModal.tsx
│       │   ├── DepartmentTree.tsx
│       │   ├── RoleList.tsx
│       │   └── MemberSearch.tsx
│       │
│       ├── FormSelector/         # 表单模板选择器
│       │   └── FormSelectorModal.tsx
│       │
│       └── VariableSelector/     # BPMN 变量选择器
│           └── VariableSelectorModal.tsx
│
├── hooks/
│   ├── useWorkflowState.ts       # 工作流状态管理
│   ├── useBpmnModeler.ts         # BPMN modeler hook
│   ├── useFormEditor.ts          # 表单编辑 hook
│   ├── useMembershipMCP.ts       # Membership MCP 集成
│   ├── useBpmnMCP.ts             # BPMN MCP 集成
│   └── useFormMCP.ts             # Form MCP 集成
│
├── services/
│   ├── workflowApi.ts            # 工作流 API
│   ├── membershipApi.ts          # Membership API
│   └── validators/
│       ├── bpmnValidator.ts      # 前端 BPMN 验证
│       └── formValidator.ts      # 前端表单验证
│
├── types/
│   ├── workflow.ts               # 工作流类型定义
│   ├── bpmn.ts                   # BPMN 相关类型
│   ├── form.ts                   # 表单相关类型 (BPM FormSchema)
│   └── membership.ts             # 组织架构类型
│
└── contexts/
    └── WorkflowContext.tsx       # 工作流上下文
```

### 3.2 核心组件接口

```typescript
// WorkflowDesignerPage.tsx
interface WorkflowDesignerProps {
  workflowId?: string;           // 编辑已有工作流
  templateId?: string;           // 从模板创建
  onSave?: (workflow: Workflow) => void;
}

// ProcessEditor.tsx
interface ProcessEditorProps {
  bpmnXml: string;
  onBpmnChange: (xml: string) => void;
  onElementSelect: (element: BpmnElement | null) => void;
  selectedElement: BpmnElement | null;
  validationMode: 'design' | 'production';
  readOnly?: boolean;
}

// FormEditor.tsx
interface FormEditorProps {
  formDefinition: FormDefinition;
  onFormChange: (form: FormDefinition) => void;
  onControlSelect: (control: FormControl | null) => void;
  selectedControl: FormControl | null;
  bpmnVariables?: BpmnVariable[];  // 用于变量绑定
  readOnly?: boolean;
}

// ChatPanel.tsx
interface ChatPanelProps {
  onApplyToProcess: (bpmnXml: string) => void;
  onApplyToForm: (formDef: FormDefinition) => void;
  currentContext: {
    bpmnXml: string;
    formDefinition: FormDefinition;
    selectedElement?: BpmnElement;
  };
}

// MembershipSelectorModal.tsx
interface MembershipSelectorModalProps {
  open: boolean;
  onClose: () => void;
  mode: 'single' | 'multiple';
  allowedTypes: ('department' | 'role' | 'member')[];
  initialSelection?: MembershipEntity[];
  onConfirm: (selected: MembershipEntity[]) => void;
}

// PropertiesPanel.tsx
interface PropertiesPanelProps {
  open: boolean;
  onClose: () => void;
  activeTab: 'process' | 'form' | 'bindings';
  selectedElement: BpmnElement | FormControl | Binding | null;
  onPropertyChange: (property: string, value: any) => void;
}
```

## 4. Data Models

### 4.1 Workflow 数据结构

```typescript
interface Workflow {
  id: string;
  name: string;
  description?: string;
  version: string;
  status: 'draft' | 'published' | 'archived';

  // BPMN 流程定义
  process: {
    bpmnXml: string;
    processId: string;
    processName: string;
  };

  // 表单定义 (多个表单)
  forms: FormDefinition[];

  // 绑定关系
  bindings: TaskFormBinding[];

  // 元数据
  metadata: {
    createdAt: string;
    updatedAt: string;
    createdBy: string;
    tenantId: string;
  };
}

interface TaskFormBinding {
  id: string;
  taskId: string;           // BPMN UserTask ID
  taskName: string;
  formId: string;           // Form Definition ID
  formName: string;

  // 权限同步配置
  permissionSync: {
    enabled: boolean;
    sourceType: 'executor' | 'custom';
    customRules?: PermissionRule[];
  };

  // 变量映射
  variableMappings: {
    formControlId: string;
    bpmnVariableName: string;
    direction: 'input' | 'output' | 'both';
  }[];
}
```

### 4.2 FormDefinition (BPM FormSchema 对齐)

```typescript
interface FormDefinition {
  formId: string;
  version: string;
  title: string;
  description?: string;

  // 使用 controls 而非 fields (BPM 对齐)
  controls: FormControl[];

  // 表单级验证规则
  validation?: {
    rules: Record<string, ValidationRule[]>;
    crossFieldRules?: CrossFieldRule[];
  };

  // 表单类型
  formType: 'standalone' | 'task_bound' | 'start_form';

  // 布局配置
  layout?: {
    columns: number;
    labelPosition: 'top' | 'left' | 'inline';
  };
}

interface FormControl {
  id: string;
  type: ControlType;         // 37 种控件类型
  label: string;

  // 控件属性
  props: Record<string, any>;

  // 布局
  width: string;             // "100%" | "50%" | "33.33%"

  // 权限配置
  permissions?: {
    view: PermissionCondition;
    edit: PermissionCondition;
    required: PermissionCondition;
  };

  // BPMN 变量绑定
  dataBinding?: {
    bpmnVariable: string;
    sourceType: 'user_input' | 'process_variable' | 'computed';
  };

  // 嵌套控件 (用于 section, tabs 等布局控件)
  children?: FormControl[];

  // 验证规则
  validationRules?: ValidationRule[];
}

// 37 种 BPM 控件类型
type ControlType =
  // 基础输入 (8)
  | 'text' | 'textarea' | 'number' | 'email' | 'phone' | 'password' | 'url' | 'hidden'
  // 选择控件 (7)
  | 'radio' | 'checkbox' | 'select' | 'multiselect' | 'cascader' | 'treeselect' | 'transfer'
  // 日期时间 (4)
  | 'date' | 'time' | 'datetime' | 'daterange'
  // 高级输入 (6)
  | 'richtext' | 'markdown' | 'code' | 'color' | 'slider' | 'rate'
  // 文件媒体 (4)
  | 'upload' | 'image' | 'video' | 'audio'
  // 布局控件 (4)
  | 'section' | 'tabs' | 'columns' | 'divider'
  // 特殊控件 (2)
  | 'signature' | 'location'
  // 业务控件 (2)
  | 'user_selector' | 'department_selector';

interface PermissionCondition {
  condition: string;          // "*" | "role:xxx" | "expr:..."
  appliesTo: string[];        // ["*"] | ["role:approver", "dept:finance"]
}
```

### 4.3 Membership 数据结构

```typescript
interface MembershipEntity {
  id: string;
  type: 'department' | 'role' | 'member';
  name: string;
  path?: string;              // 组织路径: "公司/技术部/前端组"
  metadata?: Record<string, any>;
}

interface Department extends MembershipEntity {
  type: 'department';
  parentId?: string;
  children?: Department[];
  memberCount: number;
}

interface Role extends MembershipEntity {
  type: 'role';
  description?: string;
  permissions?: string[];
}

interface Member extends MembershipEntity {
  type: 'member';
  email?: string;
  departmentId: string;
  departmentName: string;
  roles: string[];
}

// 组织上下文 (从 Membership MCP 获取)
interface OrgContext {
  departments: Department[];
  roles: Role[];
  members: Member[];
}
```

## 5. MCP Integration

### 5.1 集成点

```typescript
// hooks/useBpmnMCP.ts
const useBpmnMCP = () => {
  const generateProcess = async (description: string, orgContext: OrgContext) => {
    // 调用 BPMN-MCP generate_process tool
    const response = await fetch('/api/v1/mcp/bpmn_mcp/tools/generate_process', {
      method: 'POST',
      body: JSON.stringify({
        tenant_id: currentTenantId,
        description,
        org_context: orgContext,
        use_real_llm: true
      })
    });
    return response.json();
  };

  const validateProcess = async (bpmnXml: string) => {
    // 调用 BPMN-MCP validate_process tool
  };

  const suggestExecutors = async (taskDescription: string) => {
    // 调用 BPMN-MCP suggest_executors tool
  };

  return { generateProcess, validateProcess, suggestExecutors };
};

// hooks/useFormMCP.ts
const useFormMCP = () => {
  const generateForm = async (description: string, formType: string) => {
    // 调用 FORM-MCP generate_form tool
  };

  const validateForm = async (formDefinition: FormDefinition) => {
    // 调用 FORM-MCP validate_form tool
  };

  const bindFormToProcess = async (formId: string, taskId: string, bpmnXml: string) => {
    // 调用 FORM-MCP bind_form_to_process tool
  };

  return { generateForm, validateForm, bindFormToProcess };
};

// hooks/useMembershipMCP.ts
const useMembershipMCP = () => {
  const getOrgContext = async () => {
    // 调用 Membership-MCP 获取组织上下文
    const response = await fetch('/api/v1/mcp/membership_mcp/tools/get_org_structure', {
      method: 'POST',
      body: JSON.stringify({ tenant_id: currentTenantId })
    });
    return response.json();
  };

  const searchMembers = async (query: string) => {
    // 搜索成员
  };

  const getDepartmentTree = async () => {
    // 获取部门树
  };

  return { getOrgContext, searchMembers, getDepartmentTree };
};
```

### 5.2 AI Chat 集成

```typescript
// ChatPanel 与 MCP 的交互流程
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;

  // AI 生成的内容
  generatedContent?: {
    type: 'bpmn' | 'form' | 'both';
    bpmnXml?: string;
    formDefinition?: FormDefinition;
    preview?: string;         // 人类可读的预览描述
  };

  // 用户操作
  actions?: {
    applied?: boolean;
    appliedAt?: string;
    modified?: boolean;
  };
}

// Chat 处理流程
const handleChatSubmit = async (message: string) => {
  // 1. 分析用户意图
  const intent = analyzeIntent(message);

  // 2. 根据意图调用相应 MCP
  if (intent.type === 'generate_process') {
    const result = await bpmnMCP.generateProcess(message, orgContext);
    return {
      generatedContent: {
        type: 'bpmn',
        bpmnXml: result.bpmn_xml,
        preview: `生成了包含 ${result.node_count} 个节点的流程`
      }
    };
  }

  if (intent.type === 'generate_form') {
    const result = await formMCP.generateForm(message, 'task_bound');
    return {
      generatedContent: {
        type: 'form',
        formDefinition: result.form_definition,
        preview: `生成了包含 ${result.field_count} 个字段的表单`
      }
    };
  }

  // 3. 同时生成流程和表单
  if (intent.type === 'generate_workflow') {
    // 并行调用
    const [processResult, formResult] = await Promise.all([
      bpmnMCP.generateProcess(message, orgContext),
      formMCP.generateForm(message, 'task_bound')
    ]);
    // ...
  }
};
```

## 6. Validation Strategy

### 6.1 验证模式

```typescript
interface ValidationConfig {
  mode: 'design' | 'production';

  // 设计模式配置
  designMode: {
    skipMembershipValidation: boolean;    // 跳过 Membership 实体验证
    skipApiValidation: boolean;           // 跳过后端 API 验证
    useMockOrgContext: boolean;           // 使用模拟组织数据
    mockOrgContext?: OrgContext;
  };

  // 生产模式配置
  productionMode: {
    validateMembership: boolean;          // 验证 Membership 实体存在
    validatePermissions: boolean;         // 验证权限配置有效
    validateBindings: boolean;            // 验证绑定关系完整
  };
}

// 默认设计模式配置
const defaultDesignConfig: ValidationConfig = {
  mode: 'design',
  designMode: {
    skipMembershipValidation: true,
    skipApiValidation: false,
    useMockOrgContext: true,
    mockOrgContext: {
      departments: [
        { id: 'mock_dept_1', type: 'department', name: '示例部门', memberCount: 10 }
      ],
      roles: [
        { id: 'mock_role_1', type: 'role', name: '审批人' },
        { id: 'mock_role_2', type: 'role', name: '经理' }
      ],
      members: []
    }
  },
  productionMode: {
    validateMembership: true,
    validatePermissions: true,
    validateBindings: true
  }
};
```

### 6.2 前端验证规则

```typescript
// BPMN 验证
const validateBpmnDesignMode = (bpmnXml: string): ValidationResult => {
  const errors: string[] = [];
  const warnings: string[] = [];

  // 1. XML 结构验证
  try {
    parseXml(bpmnXml);
  } catch (e) {
    errors.push(`XML 解析错误: ${e.message}`);
    return { valid: false, errors, warnings };
  }

  // 2. 必需元素检查
  if (!hasStartEvent(bpmnXml)) {
    errors.push('缺少开始事件 (StartEvent)');
  }
  if (!hasEndEvent(bpmnXml)) {
    errors.push('缺少结束事件 (EndEvent)');
  }

  // 3. 连接完整性检查
  const brokenFlows = findBrokenSequenceFlows(bpmnXml);
  brokenFlows.forEach(flow => {
    errors.push(`断开的连接: ${flow.id}`);
  });

  // 4. 执行者配置检查 (警告级别，设计模式下不阻断)
  const tasksWithoutExecutor = findTasksWithoutExecutor(bpmnXml);
  tasksWithoutExecutor.forEach(task => {
    warnings.push(`任务 "${task.name}" 未配置执行者`);
  });

  return {
    valid: errors.length === 0,
    errors,
    warnings
  };
};

// 表单验证
const validateFormDesignMode = (form: FormDefinition): ValidationResult => {
  const errors: string[] = [];
  const warnings: string[] = [];

  // 1. 控件类型验证
  form.controls.forEach(control => {
    if (!isValidControlType(control.type)) {
      errors.push(`无效的控件类型: ${control.type}`);
    }
  });

  // 2. 权限配置检查 (警告级别)
  form.controls.forEach(control => {
    if (!control.permissions) {
      warnings.push(`控件 "${control.label}" 未配置权限规则`);
    }
  });

  // 3. 变量绑定检查 (警告级别)
  form.controls.forEach(control => {
    if (!control.dataBinding) {
      warnings.push(`控件 "${control.label}" 未绑定 BPMN 变量`);
    }
  });

  return {
    valid: errors.length === 0,
    errors,
    warnings
  };
};
```

## 7. User Interactions

### 7.1 核心交互流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        创建新工作流                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 用户进入 Workflow Designer                                  │
│     ↓                                                           │
│  2. AI Chat: "描述你想创建的流程"                                │
│     ↓                                                           │
│  3. 用户: "创建一个三级审批的请假流程"                           │
│     ↓                                                           │
│  4. AI 调用 BPMN-MCP 生成流程                                   │
│     ↓                                                           │
│  5. Chat 显示预览: "已生成包含 5 个节点的流程"                   │
│     [应用到画布] [修改] [重新生成]                               │
│     ↓                                                           │
│  6. 用户点击 [应用到画布]                                        │
│     ↓                                                           │
│  7. ProcessEditor 显示生成的 BPMN 流程                          │
│     ↓                                                           │
│  8. 用户双击 UserTask 节点                                      │
│     ↓                                                           │
│  9. Properties Panel 滑出，显示节点属性                          │
│     ↓                                                           │
│  10. 用户点击 "执行者: [点击选择...]"                           │
│     ↓                                                           │
│  11. MembershipSelectorModal 弹出                               │
│      - 从 Membership MCP 加载组织数据                           │
│      - 用户选择角色/部门                                        │
│     ↓                                                           │
│  12. 用户点击 "表单绑定: [点击选择...]"                         │
│     ↓                                                           │
│  13. FormSelectorModal 弹出                                     │
│      - 显示已有表单模板                                         │
│      - 或选择 [新建表单]                                        │
│     ↓                                                           │
│  14. 用户选择新建，切换到 Form Tab                              │
│     ↓                                                           │
│  15. AI Chat: "为这个审批任务生成表单"                          │
│     ↓                                                           │
│  16. FormEditor 显示生成的表单                                  │
│     ↓                                                           │
│  17. 用户微调字段，配置权限                                     │
│     ↓                                                           │
│  18. 切换到 Bindings Tab 查看绑定关系                           │
│     ↓                                                           │
│  19. 验证通过，点击 [Save]                                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 快捷操作

| 操作 | 触发方式 | 结果 |
|------|---------|------|
| 打开属性面板 | 双击元素 / 点击 ⚙️ | Properties Panel 滑出 |
| 关闭属性面板 | 点击 × / 点击空白区域 / ESC | Properties Panel 收起 |
| 选择执行者 | 点击执行者输入框 | MembershipSelector 弹出 |
| 绑定表单 | 点击表单绑定输入框 | FormSelector 弹出 |
| 绑定变量 | 点击变量绑定输入框 | VariableSelector 弹出 |
| AI 生成 | 在 Chat 中输入描述 | 生成内容并预览 |
| 应用生成内容 | 点击 [应用] 按钮 | 更新对应 Editor |
| Tab 切换 | 点击 Tab | 切换编辑器视图 |
| 保存 | 点击 [Save] / Ctrl+S | 保存工作流 |
| 预览 | 点击 [Preview] | 打开预览模式 |

## 8. Implementation Plan

### Phase 1: 基础框架 (Week 1)

| 任务 | 优先级 | 预估工作量 |
|------|--------|-----------|
| WorkflowDesignerPage 布局 | P0 | 0.5d |
| Tab 切换机制 | P0 | 0.5d |
| ProcessEditor 集成 bpmn-js | P0 | 1d |
| FormEditor 基础画布 | P0 | 1d |
| Properties Panel (滑出式) | P0 | 0.5d |
| Chat Panel 基础 UI | P1 | 0.5d |

### Phase 2: 控件与属性 (Week 2)

| 任务 | 优先级 | 预估工作量 |
|------|--------|-----------|
| ControlPalette (37 种控件) | P0 | 1d |
| ControlRenderer (控件渲染) | P0 | 1.5d |
| ProcessProperties 编辑器 | P0 | 0.5d |
| FormFieldProperties 编辑器 | P0 | 0.5d |
| ExecutorConfigEditor | P0 | 0.5d |
| PermissionRuleEditor | P1 | 0.5d |

### Phase 3: MCP 集成 (Week 3)

| 任务 | 优先级 | 预估工作量 |
|------|--------|-----------|
| useMembershipMCP hook | P0 | 0.5d |
| MembershipSelectorModal | P0 | 1d |
| useBpmnMCP hook | P0 | 0.5d |
| useFormMCP hook | P0 | 0.5d |
| Chat 与 MCP 集成 | P0 | 1d |
| PreviewActions 组件 | P1 | 0.5d |

### Phase 4: 绑定与验证 (Week 4)

| 任务 | 优先级 | 预估工作量 |
|------|--------|-----------|
| BindingsView 组件 | P0 | 1d |
| TaskFormBinding 管理 | P0 | 0.5d |
| 前端 BPMN 验证器 | P0 | 0.5d |
| 前端 Form 验证器 | P0 | 0.5d |
| ValidationBar 组件 | P1 | 0.5d |
| 权限同步机制 | P1 | 1d |

### Phase 5: 测试与优化 (Week 5)

| 任务 | 优先级 | 预估工作量 |
|------|--------|-----------|
| 单元测试 | P0 | 1.5d |
| 集成测试 | P0 | 1d |
| E2E 测试 | P1 | 1d |
| 性能优化 | P1 | 0.5d |
| 文档更新 | P1 | 0.5d |

## 9. Technical Dependencies

### 9.1 前端依赖

```json
{
  "dependencies": {
    "bpmn-js": "^17.0.0",           // BPMN 建模器
    "bpmn-js-properties-panel": "^5.0.0",
    "@bpmn-io/form-js": "^1.0.0",   // 可选: 表单渲染
    "react-dnd": "^16.0.0",         // 拖拽功能
    "react-dnd-html5-backend": "^16.0.0",
    "zustand": "^4.5.0",            // 状态管理
    "@tanstack/react-query": "^5.0.0",  // 数据获取
    "tailwindcss": "^3.4.0",        // 样式
    "lucide-react": "^0.300.0"      // 图标
  }
}
```

### 9.2 后端依赖

- BPMN-MCP Server (已实现)
- FORM-MCP Server (已实现)
- Membership-MCP Server (已实现)
- LLM Integration Module (已实现)

## 10. Success Criteria

- [ ] 可以通过 AI Chat 生成 BPMN 流程
- [ ] 可以通过 AI Chat 生成表单
- [ ] 可以手动编辑 BPMN 流程
- [ ] 可以手动编辑表单 (支持 37 种控件)
- [ ] 可以从 Membership 选择执行者
- [ ] 可以绑定表单到 UserTask
- [ ] 前端验证实时反馈
- [ ] Tab 切换时状态保持
- [ ] 响应式布局正常工作
- [ ] 保存/加载工作流正常工作

---

**Document Version History**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-01-14 | AI | Initial design document |
