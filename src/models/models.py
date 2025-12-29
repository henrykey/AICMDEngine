from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class TaskRequestContext(BaseModel):
    tenant_id: Optional[str] = Field(None, alias="tenantId")
    command_set_names: Optional[List[str]] = Field(None, alias="commandSetNames") 
    user_id: Optional[str] = Field(None, alias="userId")

class ConversationMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class TaskRequest(BaseModel):
    goal: str
    context: Optional[TaskRequestContext] = None
    conversation_history: Optional[List[ConversationMessage]] = Field(None, alias="conversationHistory")

class PlanStep(BaseModel):
    step: int
    description: str
    command: str
    params: Dict[str, Any] = {} # pathParams, queryParams, body

class RiskAssessment(BaseModel):
    level: str # normal, high, critical
    message: Optional[str] = None

class TaskPlanResponse(BaseModel):
    type: str = "plan_ready" # plan_ready, clarification_needed
    confidence: float
    plan: Optional[List[PlanStep]] = None
    question: Optional[str] = None
    risk_assessment: Optional[RiskAssessment] = Field(None, alias="risk_assessment")
