from fastapi import APIRouter, Request, Depends, HTTPException
from src.models.models import TaskRequest, TaskPlanResponse
from src.core.deps import get_tenant_id
from src.services.planning_engine import PlanningEngine
from src.services.task_mode_selector import TaskModeSelector
from src.utils.request_auth import extract_bearer_token, extract_user_id
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
mode_selector = TaskModeSelector()

def get_planning_engine(request: Request) -> PlanningEngine:
    return PlanningEngine(
        request.app.mongodb,
        getattr(request.app, 'mcp_registry', None),
        getattr(request.app, 'command_retriever', None)
    )

@router.post("/", response_model=TaskPlanResponse)
async def create_task(
    task_request: TaskRequest,
    http_request: Request,
    tenant_id: int = Depends(get_tenant_id),
    engine: PlanningEngine = Depends(get_planning_engine)
):
    """
    Plan a task based on natural language goal.
    """
    # Extract Authorization header from HTTP request (same as execute router)
    auth_token = extract_bearer_token(http_request)
    user_id = extract_user_id(http_request, auth_token)
    if auth_token:
        logger.debug("Auth token extracted for planning request")
    else:
        logger.debug("No bearer token provided for planning request")
    
    requested_mode = task_request.context.planning_mode if task_request.context else None
    resolved_mode = mode_selector.resolve_mode(task_request.goal, requested_mode)

    if resolved_mode == "mcp":
        direct_mcp_executor = getattr(http_request.app, "direct_mcp_executor", None)
        if direct_mcp_executor:
            direct_result = await direct_mcp_executor.try_execute(
                goal=task_request.goal,
                tenant_id=tenant_id,
                auth_token=auth_token,
                user_id=user_id,
                candidate_limit=task_request.context.candidate_limit if task_request.context else None,
                preferred_mcp_servers=task_request.context.preferred_mcp_servers if task_request.context else None,
                requested_mode=requested_mode or "auto",
            )
            if direct_result:
                return direct_result

    response = await engine.plan_task(task_request, tenant_id, user_id=user_id, auth_token=auth_token)
    return response

