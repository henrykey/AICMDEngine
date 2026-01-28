from fastapi import APIRouter, Request, Depends, HTTPException
from src.models.models import TaskRequest, TaskPlanResponse
from src.core.deps import get_tenant_id
from src.services.planning_engine import PlanningEngine
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

def get_planning_engine(request: Request) -> PlanningEngine:
    return PlanningEngine(request.app.mongodb, getattr(request.app, 'mcp_registry', None))

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
    auth_token = None
    all_headers = dict(http_request.headers)
    logger.info(f"📨 Request headers: {all_headers}")
    auth_header = http_request.headers.get("Authorization", "")
    logger.info(f"📨 Authorization header value: '{auth_header}'")
    if auth_header.startswith("Bearer "):
        auth_token = auth_header[7:]  # Remove "Bearer " prefix
        logger.info(f"✅ AUTH TOKEN EXTRACTED: {auth_token}")
    else:
        logger.warning(f"❌ NO BEARER TOKEN IN HEADER, auth_header='{auth_header}'")
    
    response = await engine.plan_task(task_request, tenant_id, auth_token=auth_token)
    return response




