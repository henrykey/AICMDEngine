from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator, ConfigDict
from datetime import datetime
from enum import Enum
from bson import ObjectId


class ExecutionStatus(str, Enum):
    """执行状态枚举"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_FAILED = "partial_failed"
    TIMEOUT = "timeout"
    ROLLBACK = "rollback"


class StepStatus(str, Enum):
    """步骤状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLBACK = "rollback"


class ExecutionRecord(BaseModel):
    """执行记录"""
    id: Optional[str] = Field(None, alias="_id")
    tenant_id: int
    plan_id: str  # 关联到原始计划
    status: ExecutionStatus = Field(default=ExecutionStatus.RUNNING)
    total_steps: int
    completed_steps: int = 0
    failed_steps: int = 0
    global_timeout: int  # 秒
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    created_by: str  # user_id
    error_message: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def convert_objectid(cls, data: Any) -> Any:
        """Convert MongoDB ObjectId to string before validation"""
        if isinstance(data, dict):
            if '_id' in data and isinstance(data['_id'], ObjectId):
                data['_id'] = str(data['_id'])
        return data

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True
    )


class StepExecution(BaseModel):
    """步骤执行记录"""
    id: Optional[str] = Field(None, alias="_id")
    execution_id: str  # 关联到 ExecutionRecord
    step_number: int
    command: str  # 如 "POST /users"
    description: str
    status: StepStatus = Field(default=StepStatus.PENDING)
    timeout: int = Field(default=30)  # 秒
    request_data: Dict[str, Any] = Field(default_factory=dict)  # 实际发送的请求
    response_data: Optional[Dict[str, Any]] = None  # API 响应
    result_content: Optional[str] = None  # Human-readable result content from MCP tools
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rollback_command: Optional[str] = None  # 撤销命令
    rollback_status: Optional[str] = None  # pending, success, failed, skipped

    @model_validator(mode='before')
    @classmethod
    def convert_objectid(cls, data: Any) -> Any:
        """Convert MongoDB ObjectId to string before validation"""
        if isinstance(data, dict):
            if '_id' in data and isinstance(data['_id'], ObjectId):
                data['_id'] = str(data['_id'])
        return data

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True
    )


class ExecutionRequest(BaseModel):
    """执行请求"""
    plan: list  # List[PlanStep]
    global_timeout: int = Field(default=60, description="全局超时时间（秒）")
    # 可选：直接传递认证信息
    auth_token: Optional[str] = None  # JWT token

    @model_validator(mode='after')
    def validate_plan(self):
        """Validate that plan is not empty and contains valid steps"""
        if not self.plan:
            raise ValueError("Plan cannot be empty")
        if not isinstance(self.plan, list):
            raise ValueError("Plan must be a list")
        if len(self.plan) == 0:
            raise ValueError("Plan must contain at least one step")
        return self


class ExecutionResponse(BaseModel):
    """执行响应"""
    execution_id: str
    status: ExecutionStatus
    total_steps: int
    started_at: datetime

    model_config = ConfigDict(
        use_enum_values=True
    )


class ExecutionDetailResponse(BaseModel):
    """执行详情响应"""
    execution_id: str
    status: ExecutionStatus
    total_steps: int
    completed_steps: int
    failed_steps: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    steps: list  # List[StepExecution]

    model_config = ConfigDict(
        use_enum_values=True
    )


class RollbackRequest(BaseModel):
    """回滚请求"""
    rollback_from_step: int = Field(description="从第几步开始回滚（含该步）")


class RollbackResponse(BaseModel):
    """回滚响应"""
    status: str
    rolled_back_steps: int
    message: str