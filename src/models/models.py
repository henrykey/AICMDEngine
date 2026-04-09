from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class TaskRequestContext(BaseModel):
    tenant_id: Optional[str] = Field(None, alias="tenantId")
    command_set_names: Optional[List[str]] = Field(None, alias="commandSetNames") 
    user_id: Optional[str] = Field(None, alias="userId")
    planning_mode: Optional[str] = Field(None, alias="planningMode")
    retrieval_backend: Optional[str] = Field(None, alias="retrievalBackend")
    candidate_limit: Optional[int] = Field(None, alias="candidateLimit")
    include_system_state: Optional[bool] = Field(None, alias="includeSystemState")
    preferred_sources: Optional[List[str]] = Field(None, alias="preferredSources")
    preferred_mcp_servers: Optional[List[str]] = Field(None, alias="preferredMcpServers")

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


class RetrievalDiagnostics(BaseModel):
    requested_retrieval_backend: Optional[str] = None
    retrieval_backend: Optional[str] = None
    remote_candidate_count: int = 0
    remote_top_score: Optional[float] = None
    remote_fallback_reason: Optional[str] = None
    local_fallback_reason: Optional[str] = None
    keyword_hits: int = 0
    vector_hits: int = 0
    raw_candidate_count: int = 0
    prompt_candidate_count: int = 0
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    requested_mode: Optional[str] = None
    resolved_mode: Optional[str] = None
    system_state_loaded: Optional[bool] = None
    top_commands: List[str] = []


class DirectResult(BaseModel):
    server_name: str = Field(..., alias="serverName")
    tool_name: str = Field(..., alias="toolName")
    params: Dict[str, Any] = {}
    content: str
    data: Dict[str, Any] = {}

class TaskPlanResponse(BaseModel):
    type: str = "plan_ready" # plan_ready, clarification_needed
    confidence: float
    plan: Optional[List[PlanStep]] = None
    question: Optional[str] = None
    risk_assessment: Optional[RiskAssessment] = Field(None, alias="risk_assessment")
    resolved_mode: Optional[str] = Field(None, alias="resolvedMode")
    retrieval_diagnostics: Optional[RetrievalDiagnostics] = Field(None, alias="retrievalDiagnostics")
    direct_result: Optional[DirectResult] = Field(None, alias="directResult")
