"""
FORM-MCP 数据模型 - 与 BPM FormSchema 对齐
"""
from typing import Dict, List, Optional, Any, Literal, Union
from dataclasses import dataclass, field
from enum import Enum

# 37种控件类型
class ControlType(str, Enum):
    # 基础输入 (8)
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"
    PASSWORD = "password"
    EMAIL = "email"

    # 选择控件 (6)
    RADIO = "radio"
    CHECKBOX = "checkbox"
    SELECT = "select"
    CASCADER = "cascader"
    TREE_SELECT = "tree-select"
    SWITCH = "switch"

    # 高级输入 (7)
    RICHTEXT = "richtext"
    FILE_UPLOAD = "file-upload"
    IMAGE_UPLOAD = "image-upload"
    SIGNATURE = "signature"
    RATING = "rating"
    COLOR = "color"
    SLIDER = "slider"

    # 布局容器 (4)
    GRID = "grid"
    TABS = "tabs"
    COLLAPSE = "collapse"
    FLEX_CONTAINER = "flex-container"

    # 特殊控件 (5)
    SUBFORM = "subform"
    ADDRESS = "address"
    RELATION = "relation"
    DATA_TABLE = "data-table"
    COMPUTED_FIELD = "computed-field"

    # 业务控件 (4)
    MEMBER_SELECTOR = "member-selector"
    ROLE_SELECTOR = "role-selector"
    ORG_SELECTOR = "org-selector"
    PROCESS_SELECTOR = "process-selector"

    # 展示控件 (4)
    TITLE = "title"
    DESCRIPTION = "description"
    DIVIDER = "divider"
    HTML = "html"

class WidthType(str, Enum):
    """控件宽度类型"""
    FULL = "100%"
    HALF = "50%"
    THIRD = "33%"
    QUARTER = "25%"
    AUTO = "auto"

@dataclass
class ValidationRule:
    """验证规则 - 对齐 BPM ValidationRule"""
    type: str  # required, email, pattern, min, max, minLength, maxLength, custom
    message: str
    value: Optional[Any] = None  # min/max/minLength/maxLength 的值
    pattern: Optional[str] = None  # pattern 类型的正则表达式
    validate: Optional[str] = None  # custom 类型的验证表达式

@dataclass
class FlexItemProps:
    """Flex 布局属性"""
    flex: Optional[str] = None
    justifyContent: Optional[str] = None
    alignItems: Optional[str] = None
    gap: Optional[str] = None

@dataclass
class FormControlInstance:
    """
    表单控件实例 - 与 BPM FormControlInstance 对齐
    """
    id: str  # 唯一 ID (nanoid 风格)
    type: str  # ControlType 之一
    label: str  # 控件标签
    props: Dict[str, Any]  # 控件属性 (placeholder, required 等)
    children: Optional[List['FormControlInstance']] = None  # 子控件 (嵌套容器)
    flexProps: Optional[FlexItemProps] = None  # Flex 布局属性
    width: Optional[str] = None  # 宽度: 100% | 50% | 33% | 25% | auto
    cellIndex: Optional[int] = None  # Grid 单元格索引
    tabKey: Optional[str] = None  # Tab 键值
    panelKey: Optional[str] = None  # Collapse 面板键值

@dataclass
class FieldPermissions:
    """字段级权限 - FORM-MCP 增强"""
    view: Optional[Dict[str, Any]] = None  # { "condition": "...", "applies_to": [...] }
    edit: Optional[Dict[str, Any]] = None
    required: Optional[Dict[str, Any]] = None

@dataclass
class DataBinding:
    """BPMN 流程变量绑定 - FORM-MCP 增强"""
    bpmn_variable: str
    source_type: str  # user_input | calculated | from_membership | from_kb
    source_config: Optional[Dict[str, Any]] = None

@dataclass
class FormControlInstanceWithPermissions(FormControlInstance):
    """
    扩展的表单控件实例 - 包含 FORM-MCP 增强
    """
    permissions: Optional[FieldPermissions] = None  # 字段级权限
    data_binding: Optional[DataBinding] = None  # BPMN 绑定
    validation: Optional[List[ValidationRule]] = None  # 完整验证规则

@dataclass
class FormSchema:
    """
    完整表单定义 - 与 BPM FormSchema 对齐
    """
    # 基础信息
    formId: str
    version: str
    title: str
    description: Optional[str] = None

    # 控件配置
    controls: List[Union[FormControlInstance, FormControlInstanceWithPermissions]] = field(default_factory=list)

    # 验证规则
    validation: Optional[Dict[str, Any]] = None  # { "rules": { "field-id": [...] } }

    # 元数据
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    createdBy: Optional[str] = None

    # FORM-MCP 增强字段
    form_type: Optional[str] = None  # startup | task_specific | standalone
    bpmn_bindings: Optional[Dict[str, Any]] = None  # BPMN 流程变量映射
    confidence_score: Optional[float] = None  # 0.0-1.0
    validation_warnings: Optional[List[str]] = None

# 向后兼容: 别名
FormDefinition = FormSchema
