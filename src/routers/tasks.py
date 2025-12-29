from fastapi import APIRouter, Request, Depends, HTTPException
from src.models.models import TaskRequest, TaskPlanResponse
from src.core.deps import get_tenant_id
from src.services.planning_engine import PlanningEngine

router = APIRouter()

def get_planning_engine(request: Request) -> PlanningEngine:
    return PlanningEngine(request.app.mongodb)

@router.post("/", response_model=TaskPlanResponse)
async def create_task(
    request: TaskRequest,
    tenant_id: str = Depends(get_tenant_id),
    engine: PlanningEngine = Depends(get_planning_engine)
):
    """
    Plan a task based on natural language goal.
    """
    # If context is not provided in body, we can initialize it (though Pydantic handles parsing) or strict check 
    # Logic: Header Tenant ID is the truth.
    
    # Delegate to Engine
    # Note: request.context.tenantId is optional in body, 
    # but for Public Mode mismatch check, we could do it here or relying on pure Header trust.
    # The deps.get_tenant_id already enforces headers logic.
    
    response = await engine.plan_task(request, tenant_id)
    return response
