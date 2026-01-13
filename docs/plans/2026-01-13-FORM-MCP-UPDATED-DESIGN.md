# FORM-MCP 更新设计文档 (BPM 对齐版本 v1.1)

**版本**: 1.1
**日期**: 2026-01-13
**状态**: 设计完成，准备实现
**对齐目标**: BPM FormSchema 标准

---

## 📋 执行摘要

FORM-MCP 已更新为完全对齐 **BPM FormSchema** 格式，同时保留其专有的增强功能：
- ✅ 支持 **37 种控件类型**（而非原来的 7 种）
- ✅ 支持 **嵌套容器** 和 **Flex 布局**
- ✅ **完整的验证规则系统**
- ✅ **字段级权限**（FORM-MCP 专有）
- ✅ **BPMN 流程变量绑定**（FORM-MCP 专有）

---

## 🏗️ 架构对比

### 原设计 vs 新设计

| 维度 | 原设计 | 新设计 | 改进 |
|------|--------|--------|------|
| **控件类型** | 7 种 | 37 种 | +30 种 |
| **容器支持** | ❌ Sections 分组 | ✅ Nested children | 支持深层嵌套 |
| **布局系统** | ❌ width 属性 | ✅ width + flexProps | Flex 完整支持 |
| **验证规则** | 简单对象 | 完整数组系统 | 支持多规则链 |
| **字段数组名** | `fields` | `controls` | BPM 标准 |
| **权限系统** | ✅ View/Edit/Required | ✅ 保留 | 保持不变 |
| **BPMN 绑定** | ✅ data_binding | ✅ 保留 | 保持不变 |

---

## 📐 完整数据格式

### FormSchema 完整结构

```typescript
interface FormSchema {
  // 基础信息 (BPM 标准)
  formId: string;                    // 唯一表单ID
  version: string;                   // 版本 (如 "1.0.0")
  title: string;                     // 表单标题
  description?: string;              // 表单描述

  // 控件配置 (BPM 标准, 37种支持)
  controls: FormControlInstance[];   // 控件数组 (支持嵌套)

  // 验证规则 (BPM 标准)
  validation?: {
    rules: {
      [controlId: string]: ValidationRule[];  // 每个控件的验证规则数组
    }
  };

  // 元数据 (BPM 标准)
  createdAt?: string;
  updatedAt?: string;
  createdBy?: string;

  // FORM-MCP 增强字段
  form_type?: "startup" | "task_specific" | "standalone";
  bpmn_bindings?: {
    process_name?: string;
    process_variables_mapped?: string[];
    unmapped_variables?: string[];
  };
  confidence_score?: number;         // 0.0-1.0
  validation_warnings?: string[];
}

interface FormControlInstance {
  // 必需字段
  id: string;                        // 唯一ID (nanoid风格)
  type: string;                      // 37种控件类型之一
  label: string;                     // 控件标签

  // 属性和布局
  props: {
    [key: string]: any;              // 控件特定属性
    required?: boolean;
    placeholder?: string;
    maxLength?: number;
    // ...
  };

  // 布局属性
  width?: "100%" | "50%" | "33%" | "25%" | "auto";  // 宽度
  flexProps?: {
    flex?: string;
    justifyContent?: string;
    alignItems?: string;
    gap?: string;
  };

  // 嵌套支持
  children?: FormControlInstance[];  // 子控件 (容器类型)
  cellIndex?: number;                // Grid 单元格索引
  tabKey?: string;                   // Tab 页签键
  panelKey?: string;                 // Collapse 面板键

  // FORM-MCP 增强
  permissions?: {
    view?: {
      condition: string;             // 例: "role:approver" 或 "*"
      applies_to: string[];          // 应用对象
    };
    edit?: {
      condition: string;
      applies_to: string[];
    };
    required?: {
      condition: string;
      applies_to: string[];
    };
  };

  data_binding?: {
    bpmn_variable: string;           // BPMN 流程变量名
    source_type: "user_input" | "calculated" | "from_membership" | "from_kb";
    source_config?: {
      entity_type?: string;          // member | role | department
      entity_name?: string;
      kb_query?: string;
    };
  };

  validation?: ValidationRule[];     // 验证规则 (可选)
}

interface ValidationRule {
  type: string;                      // required, email, pattern, min, max, minLength, maxLength, custom
  message: string;                   // 错误消息
  value?: any;                       // min/max 的值
  pattern?: string;                  // pattern 类型的正则
  validate?: string;                 // custom 类型的表达式
}
```

---

## 🎯 37 种控件类型完整列表

### 1️⃣ 基础输入 (8 种)

| 控件类型 | 说明 | Props 示例 |
|---------|------|-----------|
| `text` | 单行文本 | `{ placeholder, maxLength, pattern }` |
| `textarea` | 多行文本 | `{ rows, maxLength, autoSize }` |
| `number` | 数字输入 | `{ min, max, step, precision }` |
| `date` | 日期选择 | `{ format, disabledDate }` |
| `time` | 时间选择 | `{ format, hourStep, minuteStep }` |
| `datetime` | 日期时间 | `{ format }` |
| `password` | 密码输入 | `{ minLength, maxLength, showStrength }` |
| `email` | 邮箱输入 | `{ validation type: email }` |

### 2️⃣ 选择控件 (6 种)

| 控件类型 | 说明 | Props 示例 |
|---------|------|-----------|
| `radio` | 单选框 | `{ options, layout: horizontal\|vertical }` |
| `checkbox` | 多选框 | `{ options, min, max }` |
| `select` | 下拉选择 | `{ options, mode: single\|multiple, searchable }` |
| `cascader` | 级联选择 | `{ options, changeOnSelect, expandTrigger }` |
| `tree-select` | 树形选择 | `{ options, multiple, checkable }` |
| `switch` | 开关 | `{ defaultValue }` |

### 3️⃣ 高级输入 (7 种)

| 控件类型 | 说明 | Props 示例 |
|---------|------|-----------|
| `richtext` | 富文本编辑器 | `{ toolbar, placeholder }` |
| `file-upload` | 文件上传 | `{ accept, maxSize, multiple }` |
| `image-upload` | 图片上传 | `{ accept: image/*, maxSize, preview }` |
| `signature` | 签名板 | `{ width, height }` |
| `rating` | 评分 | `{ allowHalf, count }` |
| `color` | 颜色选择器 | `{ format: hex\|rgb }` |
| `slider` | 滑块 | `{ min, max, step, range }` |

### 4️⃣ 布局容器 (4 种)

| 控件类型 | 说明 | 特性 |
|---------|------|------|
| `grid` | 栅格容器 | 支持 children, columns, gap |
| `tabs` | 标签页 | 支持 children, tabKey, activeKey |
| `collapse` | 折叠面板 | 支持 children, panelKey, accordion |
| `flex-container` | Flex 容器 | 支持 children, flexProps |

### 5️⃣ 特殊控件 (5 种)

| 控件类型 | 说明 | 用途 |
|---------|------|------|
| `subform` | 子表单 | 嵌入另一个表单 |
| `address` | 地址选择 | 省市区地址选择 |
| `relation` | 关联选择 | 关联其他实体 |
| `data-table` | 数据表格 | 展示/编辑表格数据 |
| `computed-field` | 计算字段 | 基于其他字段计算的值 |

### 6️⃣ 业务控件 (4 种)

| 控件类型 | 说明 | 数据源 |
|---------|------|--------|
| `member-selector` | 成员选择器 | Membership API |
| `role-selector` | 角色选择器 | Membership API |
| `org-selector` | 组织选择器 | Membership API |
| `process-selector` | 流程选择器 | BPMN 流程定义 |

### 7️⃣ 展示控件 (4 种)

| 控件类型 | 说明 | 用途 |
|---------|------|------|
| `title` | 标题 | 分段标题 |
| `description` | 说明文本 | 字段或分段说明 |
| `divider` | 分割线 | 视觉分割 |
| `html` | HTML 内容 | 自定义 HTML 展示 |

---

## 📋 完整验证规则系统

### 验证规则类型

```typescript
interface ValidationRule {
  // 内置验证类型
  type:
    | "required"       // 必填
    | "email"          // 邮箱格式
    | "pattern"        // 正则匹配
    | "min"            // 最小值
    | "max"            // 最大值
    | "minLength"      // 最小长度
    | "maxLength"      // 最大长度
    | "custom";        // 自定义

  message: string;     // 错误消息

  // 类型特定的字段
  value?: number;      // min/max/minLength/maxLength 的值
  pattern?: string;    // 正则表达式 (pattern 类型)
  validate?: string;   // 验证表达式 (custom 类型)
}
```

### 使用示例

```json
{
  "controls": [
    {
      "id": "amount",
      "type": "number",
      "label": "金额",
      "props": { "required": true },
      "validation": [
        { "type": "required", "message": "金额为必填项" },
        { "type": "min", "value": 0, "message": "金额不能为负数" },
        { "type": "max", "value": 1000000, "message": "金额不能超过100万" },
        { "type": "custom", "message": "金额不能为999999", "validate": "value != 999999" }
      ]
    }
  ]
}
```

---

## 🔀 数据流转示例

### 示例 1: 简单的单行文本

```json
{
  "id": "field-1",
  "type": "text",
  "label": "姓名",
  "props": {
    "required": true,
    "placeholder": "请输入姓名",
    "maxLength": 50
  },
  "width": "100%",
  "validation": [
    { "type": "required", "message": "姓名为必填项" },
    { "type": "maxLength", "value": 50, "message": "最多50个字符" }
  ],
  "permissions": {
    "view": { "condition": "*", "applies_to": ["*"] },
    "edit": { "condition": "*", "applies_to": ["*"] },
    "required": { "condition": "*", "applies_to": ["*"] }
  },
  "data_binding": {
    "bpmn_variable": "applicant_name",
    "source_type": "user_input"
  }
}
```

### 示例 2: 嵌套的栅格容器

```json
{
  "id": "grid-1",
  "type": "grid",
  "label": "个人信息",
  "props": {
    "columns": 2,
    "gap": "16px"
  },
  "children": [
    {
      "id": "field-2",
      "type": "text",
      "label": "姓",
      "props": { "required": true },
      "width": "50%",
      "cellIndex": 0
    },
    {
      "id": "field-3",
      "type": "text",
      "label": "名",
      "props": { "required": true },
      "width": "50%",
      "cellIndex": 1
    }
  ]
}
```

### 示例 3: 带权限的业务控件

```json
{
  "id": "approver",
  "type": "member-selector",
  "label": "选择审批人",
  "props": {
    "required": true,
    "multiple": false,
    "filter": "role:approver"
  },
  "width": "100%",
  "permissions": {
    "view": { "condition": "*", "applies_to": ["*"] },
    "edit": { "condition": "role:manager", "applies_to": ["role:manager"] },
    "required": { "condition": "role:manager", "applies_to": ["role:manager"] }
  },
  "data_binding": {
    "bpmn_variable": "approval_assignee",
    "source_type": "from_membership",
    "source_config": {
      "entity_type": "member",
      "filter": "role:approver"
    }
  }
}
```

---

## 🔄 MCP 工具接口

### Tool 1: `generate_form`

**功能**: 从自然语言生成 BPM FormSchema 格式的表单

**请求参数**:
```json
{
  "form_name": "string (required)",
  "form_type": "startup|task_specific|standalone",
  "description": "string (required)",
  "context": {
    "process_name": "string (optional)",
    "departments": ["array"],
    "roles": ["array"]
  }
}
```

**响应格式**:
```json
{
  "success": true,
  "form_definition": {
    "formId": "...",
    "version": "1.0.0",
    "title": "...",
    "controls": [...],
    "validation": {...},
    "form_type": "...",
    "confidence_score": 0.95
  },
  "validation_warnings": [],
  "confidence_score": 0.95
}
```

### Tool 2: `validate_form`

**功能**: 验证表单定义的有效性

**请求参数**:
```json
{
  "form_definition": {...},
  "strict_mode": false,
  "bpmn_context": {
    "process_variables": ["array"]
  }
}
```

**响应格式**:
```json
{
  "success": true,
  "valid": true,
  "errors": [],
  "warnings": [],
  "issues": {
    "field_issues": [],
    "permission_issues": [],
    "binding_issues": []
  }
}
```

### Tool 3: `suggest_form_fields`

**功能**: 根据表单描述建议字段

**请求参数**:
```json
{
  "form_description": "string"
}
```

**响应格式**:
```json
{
  "success": true,
  "suggestions": [
    { "field_type": "text", "suggested_label": "姓名" }
  ],
  "recommended_control_types": ["text", "email", "select"]
}
```

### Tool 4: `bind_form_to_process`

**功能**: 将表单字段绑定到 BPMN 流程变量

**请求参数**:
```json
{
  "form_definition": {...},
  "process_variables": ["array"]
}
```

**响应格式**:
```json
{
  "success": true,
  "process_variables_mapped": ["array"],
  "unmapped_variables": ["array"],
  "binding_coverage": 0.95
}
```

---

## 🔄 与 ProcessEditor 的集成

### 生成流程的表单

```mermaid
graph LR
    A["用户输入"] -->|生成| B["BPMN-MCP"]
    B -->|产生| C["BPMN 流程定义"]
    C -->|提取变量| D["FORM-MCP"]
    D -->|生成| E["FormSchema"]
    E -->|导入| F["FormEditor<br/>设计表单"]
    F -->|导出| G["运行时"]
    G -->|渲染| H["用户表单"]
```

### 数据流转

```json
{
  "流程": {
    "processId": "drug-approval",
    "variables": [
      { "name": "applicant_name", "type": "string", "direction": "input" },
      { "name": "approval_decision", "type": "string", "direction": "output" }
    ]
  },
  "表单": {
    "formId": "drug-approval-startup",
    "controls": [
      {
        "id": "applicant_name",
        "type": "text",
        "data_binding": { "bpmn_variable": "applicant_name" }
      }
    ]
  }
}
```

---

## ✨ FORM-MCP 核心优势

相比原始 BPM FormSchema，FORM-MCP 增加的价值：

### 1. 智能生成
- 从自然语言自动生成表单结构
- LLM 驱动的字段建议
- 自动权限推荐

### 2. 权限管理
- 字段级权限（非表单级）
- 基于组织结构的自动权限映射
- View/Edit/Required 三层权限控制

### 3. BPMN 集成
- 自动映射流程变量到表单字段
- 支持输入/输出方向
- 变量类型匹配验证

### 4. 组织集成
- 与 Membership API 深度集成
- 自动加载部门/角色列表
- 业务控件（member-selector 等）

### 5. 知识库集成
- 与 KB MCP 集成
- 自动建议字段和数据源
- 智能字段值填充

---

## 📊 向后兼容性

### 自动格式转换

旧格式（仅供参考）:
```json
{
  "fields": [...]
}
```

新格式:
```json
{
  "controls": [...]
}
```

系统会自动转换，无需修改现有代码。

---

## 🧪 测试覆盖

- ✅ 37 种控件类型验证
- ✅ 嵌套容器验证
- ✅ 验证规则链验证
- ✅ 权限逻辑验证
- ✅ BPMN 绑定验证
- ✅ 组织上下文验证

---

## 📝 成功标准

- [ ] 生成的表单 100% 为有效 BPM FormSchema
- [ ] 支持所有 37 种控件类型
- [ ] 验证规则系统覆盖常见场景 (95%+)
- [ ] 权限逻辑正确执行
- [ ] BPMN 绑定准确率 > 90%
- [ ] 文档完整度 100%
- [ ] 测试覆盖率 > 75%

---

**文档版本**: 1.1
**最后更新**: 2026-01-13
**维护者**: AI CMD Engine 团队
