/**
 * Workflow Designer Type Definitions
 *
 * Aligned with BPM FormSchema and BPMN 2.0 standards
 */

// ============================================================================
// Workflow Types
// ============================================================================

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  version: string;
  status: 'draft' | 'published' | 'archived';

  // BPMN Process
  process: {
    bpmnXml: string;
    processId: string;
    processName: string;
  };

  // Forms (multiple forms per workflow)
  forms: FormDefinition[];

  // Task-Form Bindings
  bindings: TaskFormBinding[];

  // Metadata
  metadata: {
    createdAt: string;
    updatedAt: string;
    createdBy: string;
    tenantId: string;
  };
}

export interface TaskFormBinding {
  id: string;
  taskId: string;
  taskName: string;
  formId: string;
  formName: string;

  // Permission sync configuration
  permissionSync: {
    enabled: boolean;
    sourceType: 'executor' | 'custom';
    customRules?: PermissionCondition[];
  };

  // Variable mappings
  variableMappings: VariableMapping[];
}

export interface VariableMapping {
  formControlId: string;
  bpmnVariableName: string;
  direction: 'input' | 'output' | 'both';
}

// ============================================================================
// BPMN Types
// ============================================================================

export interface BpmnElement {
  id: string;
  type: string;
  name?: string;
  businessObject?: any;
}

export interface BpmnVariable {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'date' | 'object';
  scope: 'process' | 'task';
  taskId?: string;
}

export interface ExecutorConfig {
  pattern: ExecutorPattern;
  config: Record<string, any>;
}

export type ExecutorPattern =
  | 'static'        // Fixed role/department/member
  | 'form_driven'   // User selects at process start
  | 'dynamic'       // Data-driven routing
  | 'queue_claim'   // First-available from pool
  | 'automation';   // MCP tool or virtual member

export interface StaticExecutorConfig {
  type: 'role' | 'department' | 'member';
  value: string;
  valueId: string;
}

export interface FormDrivenExecutorConfig {
  formField: string;
  selectionType: 'role' | 'department' | 'member';
}

export interface DynamicExecutorConfig {
  mcpTool: string;
  kbQuery?: string;
}

export interface QueueClaimExecutorConfig {
  claimGroup: 'role' | 'department';
  groupName: string;
  groupId: string;
}

export interface AutomationExecutorConfig {
  automationType: 'mcp_tool' | 'virtual_member';
  mcpToolName?: string;
  virtualMemberName?: string;
}

// ============================================================================
// Form Types (BPM FormSchema Aligned)
// ============================================================================

export interface FormDefinition {
  formId: string;
  version: string;
  title: string;
  description?: string;

  // Use 'controls' instead of 'fields' (BPM alignment)
  controls: FormControl[];

  // Form-level validation
  validation?: {
    rules: Record<string, ValidationRule[]>;
    crossFieldRules?: CrossFieldRule[];
  };

  // Form type
  formType: 'standalone' | 'task_bound' | 'start_form';

  // Layout configuration
  layout?: {
    columns: number;
    labelPosition: 'top' | 'left' | 'inline';
  };

  // Confidence score (from AI generation)
  confidenceScore?: number;
}

export interface FormControl {
  id: string;
  type: ControlType;
  label: string;

  // Control properties
  props: Record<string, any>;

  // Layout
  width: ControlWidth;

  // Permissions
  permissions?: {
    view: PermissionCondition;
    edit: PermissionCondition;
    required: PermissionCondition;
  };

  // BPMN variable binding
  dataBinding?: {
    bpmnVariable: string;
    sourceType: 'user_input' | 'process_variable' | 'computed';
  };

  // Nested controls (for layout controls)
  children?: FormControl[];

  // Validation rules
  validationRules?: ValidationRule[];
}

// 37 BPM Control Types
export type ControlType =
  // Basic Input (8)
  | 'text' | 'textarea' | 'number' | 'email' | 'phone' | 'password' | 'url' | 'hidden'
  // Selection Controls (7)
  | 'radio' | 'checkbox' | 'select' | 'multiselect' | 'cascader' | 'treeselect' | 'transfer'
  // Date/Time (4)
  | 'date' | 'time' | 'datetime' | 'daterange'
  // Advanced Input (6)
  | 'richtext' | 'markdown' | 'code' | 'color' | 'slider' | 'rate'
  // File/Media (4)
  | 'upload' | 'image' | 'video' | 'audio'
  // Layout Controls (4)
  | 'section' | 'tabs' | 'columns' | 'divider'
  // Special Controls (2)
  | 'signature' | 'location'
  // Business Controls (2)
  | 'user_selector' | 'department_selector';

export type ControlWidth = '100%' | '75%' | '50%' | '33.33%' | '25%';

export interface PermissionCondition {
  condition: string;  // "*" | "role:xxx" | "expr:..."
  appliesTo: string[]; // ["*"] | ["role:approver", "dept:finance"]
}

export interface ValidationRule {
  type: 'required' | 'minLength' | 'maxLength' | 'min' | 'max' | 'pattern' | 'email' | 'url' | 'custom';
  value?: any;
  message?: string;
}

export interface CrossFieldRule {
  type: 'compare' | 'dependency' | 'custom';
  fields: string[];
  condition: string;
  message: string;
}

// ============================================================================
// Membership Types
// ============================================================================

export interface MembershipEntity {
  id: string;
  type: 'department' | 'role' | 'member';
  name: string;
  path?: string;
  metadata?: Record<string, any>;
}

export interface Department extends MembershipEntity {
  type: 'department';
  parentId?: string;
  children?: Department[];
  memberCount: number;
}

export interface Role extends MembershipEntity {
  type: 'role';
  description?: string;
  permissions?: string[];
}

export interface Member extends MembershipEntity {
  type: 'member';
  email?: string;
  departmentId: string;
  departmentName: string;
  roles: string[];
}

export interface OrgContext {
  departments: Department[];
  roles: Role[];
  members: Member[];
}

// ============================================================================
// Validation Types
// ============================================================================

export interface ValidationResult {
  valid: boolean;
  errors: ValidationMessage[];
  warnings: ValidationMessage[];
  confidenceScore?: number;
}

export interface ValidationMessage {
  code: string;
  message: string;
  elementId?: string;
  elementType?: string;
  severity: 'error' | 'warning' | 'info';
}

export interface ValidationConfig {
  mode: 'design' | 'production';
  skipMembershipValidation?: boolean;
  skipApiValidation?: boolean;
  mockOrgContext?: OrgContext;
}

// ============================================================================
// Chat Types
// ============================================================================

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;

  // Generated content from AI
  generatedContent?: {
    type: 'bpmn' | 'form' | 'both';
    bpmnXml?: string;
    formDefinition?: FormDefinition;
    preview?: string;
  };

  // User actions
  actions?: {
    applied?: boolean;
    appliedAt?: string;
    modified?: boolean;
  };
}

// ============================================================================
// Component Props Types
// ============================================================================

export interface WorkflowDesignerProps {
  workflowId?: string;
  templateId?: string;
  onSave?: (workflow: Workflow) => void;
}

export interface ProcessEditorProps {
  bpmnXml: string;
  onBpmnChange: (xml: string) => void;
  onElementSelect: (element: BpmnElement | null) => void;
  selectedElement: BpmnElement | null;
  validationMode: 'design' | 'production';
  readOnly?: boolean;
}

export interface FormEditorProps {
  formDefinition: FormDefinition;
  onFormChange: (form: FormDefinition) => void;
  onControlSelect: (control: FormControl | null) => void;
  selectedControl: FormControl | null;
  bpmnVariables?: BpmnVariable[];
  readOnly?: boolean;
}

export interface ChatPanelProps {
  onApplyToProcess: (bpmnXml: string) => void;
  onApplyToForm: (formDef: FormDefinition) => void;
  currentContext: {
    bpmnXml: string;
    formDefinition: FormDefinition;
    selectedElement?: BpmnElement;
  };
}

export interface PropertiesPanelProps {
  open: boolean;
  onClose: () => void;
  activeTab: 'process' | 'form' | 'bindings';
  selectedElement: BpmnElement | FormControl | TaskFormBinding | null;
  onPropertyChange: (property: string, value: any) => void;
}

export interface MembershipSelectorModalProps {
  open: boolean;
  onClose: () => void;
  mode: 'single' | 'multiple';
  allowedTypes: ('department' | 'role' | 'member')[];
  initialSelection?: MembershipEntity[];
  onConfirm: (selected: MembershipEntity[]) => void;
  title?: string;
}

// ============================================================================
// Control Metadata (for palette and rendering)
// ============================================================================

export interface ControlMetadata {
  type: ControlType;
  label: string;
  icon: string;
  category: ControlCategory;
  defaultProps: Record<string, any>;
  defaultWidth: ControlWidth;
}

export type ControlCategory =
  | 'basic'
  | 'selection'
  | 'datetime'
  | 'advanced'
  | 'file'
  | 'layout'
  | 'special'
  | 'business';

// Control catalog for the palette
export const CONTROL_CATALOG: ControlMetadata[] = [
  // Basic Input
  { type: 'text', label: '单行文本', icon: 'Type', category: 'basic', defaultProps: { placeholder: '' }, defaultWidth: '100%' },
  { type: 'textarea', label: '多行文本', icon: 'AlignLeft', category: 'basic', defaultProps: { rows: 4 }, defaultWidth: '100%' },
  { type: 'number', label: '数字', icon: 'Hash', category: 'basic', defaultProps: { min: 0 }, defaultWidth: '50%' },
  { type: 'email', label: '邮箱', icon: 'Mail', category: 'basic', defaultProps: {}, defaultWidth: '50%' },
  { type: 'phone', label: '电话', icon: 'Phone', category: 'basic', defaultProps: {}, defaultWidth: '50%' },
  { type: 'password', label: '密码', icon: 'Lock', category: 'basic', defaultProps: {}, defaultWidth: '50%' },
  { type: 'url', label: '网址', icon: 'Link', category: 'basic', defaultProps: {}, defaultWidth: '100%' },
  { type: 'hidden', label: '隐藏字段', icon: 'EyeOff', category: 'basic', defaultProps: {}, defaultWidth: '100%' },

  // Selection Controls
  { type: 'radio', label: '单选框', icon: 'Circle', category: 'selection', defaultProps: { options: [] }, defaultWidth: '100%' },
  { type: 'checkbox', label: '复选框', icon: 'CheckSquare', category: 'selection', defaultProps: { options: [] }, defaultWidth: '100%' },
  { type: 'select', label: '下拉选择', icon: 'ChevronDown', category: 'selection', defaultProps: { options: [] }, defaultWidth: '50%' },
  { type: 'multiselect', label: '多选下拉', icon: 'List', category: 'selection', defaultProps: { options: [] }, defaultWidth: '50%' },
  { type: 'cascader', label: '级联选择', icon: 'GitBranch', category: 'selection', defaultProps: { options: [] }, defaultWidth: '50%' },
  { type: 'treeselect', label: '树选择', icon: 'FolderTree', category: 'selection', defaultProps: { options: [] }, defaultWidth: '50%' },
  { type: 'transfer', label: '穿梭框', icon: 'ArrowLeftRight', category: 'selection', defaultProps: { options: [] }, defaultWidth: '100%' },

  // Date/Time
  { type: 'date', label: '日期', icon: 'Calendar', category: 'datetime', defaultProps: { format: 'YYYY-MM-DD' }, defaultWidth: '50%' },
  { type: 'time', label: '时间', icon: 'Clock', category: 'datetime', defaultProps: { format: 'HH:mm' }, defaultWidth: '50%' },
  { type: 'datetime', label: '日期时间', icon: 'CalendarClock', category: 'datetime', defaultProps: {}, defaultWidth: '50%' },
  { type: 'daterange', label: '日期范围', icon: 'CalendarRange', category: 'datetime', defaultProps: {}, defaultWidth: '100%' },

  // Advanced Input
  { type: 'richtext', label: '富文本', icon: 'FileText', category: 'advanced', defaultProps: {}, defaultWidth: '100%' },
  { type: 'markdown', label: 'Markdown', icon: 'FileCode', category: 'advanced', defaultProps: {}, defaultWidth: '100%' },
  { type: 'code', label: '代码', icon: 'Code', category: 'advanced', defaultProps: { language: 'javascript' }, defaultWidth: '100%' },
  { type: 'color', label: '颜色', icon: 'Palette', category: 'advanced', defaultProps: {}, defaultWidth: '25%' },
  { type: 'slider', label: '滑块', icon: 'SlidersHorizontal', category: 'advanced', defaultProps: { min: 0, max: 100 }, defaultWidth: '100%' },
  { type: 'rate', label: '评分', icon: 'Star', category: 'advanced', defaultProps: { max: 5 }, defaultWidth: '50%' },

  // File/Media
  { type: 'upload', label: '文件上传', icon: 'Upload', category: 'file', defaultProps: { accept: '*' }, defaultWidth: '100%' },
  { type: 'image', label: '图片上传', icon: 'Image', category: 'file', defaultProps: { accept: 'image/*' }, defaultWidth: '100%' },
  { type: 'video', label: '视频上传', icon: 'Video', category: 'file', defaultProps: { accept: 'video/*' }, defaultWidth: '100%' },
  { type: 'audio', label: '音频上传', icon: 'Music', category: 'file', defaultProps: { accept: 'audio/*' }, defaultWidth: '100%' },

  // Layout Controls
  { type: 'section', label: '分组', icon: 'Square', category: 'layout', defaultProps: { title: '分组标题' }, defaultWidth: '100%' },
  { type: 'tabs', label: '标签页', icon: 'Layers', category: 'layout', defaultProps: { tabs: [] }, defaultWidth: '100%' },
  { type: 'columns', label: '分栏', icon: 'Columns', category: 'layout', defaultProps: { columns: 2 }, defaultWidth: '100%' },
  { type: 'divider', label: '分割线', icon: 'Minus', category: 'layout', defaultProps: {}, defaultWidth: '100%' },

  // Special Controls
  { type: 'signature', label: '签名', icon: 'PenTool', category: 'special', defaultProps: {}, defaultWidth: '100%' },
  { type: 'location', label: '位置', icon: 'MapPin', category: 'special', defaultProps: {}, defaultWidth: '100%' },

  // Business Controls
  { type: 'user_selector', label: '人员选择', icon: 'User', category: 'business', defaultProps: { multiple: false }, defaultWidth: '50%' },
  { type: 'department_selector', label: '部门选择', icon: 'Building', category: 'business', defaultProps: { multiple: false }, defaultWidth: '50%' },
];

// Helper to get control metadata
export const getControlMetadata = (type: ControlType): ControlMetadata | undefined => {
  return CONTROL_CATALOG.find(c => c.type === type);
};

// Helper to get controls by category
export const getControlsByCategory = (category: ControlCategory): ControlMetadata[] => {
  return CONTROL_CATALOG.filter(c => c.category === category);
};
