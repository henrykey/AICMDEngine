from fastapi import APIRouter, Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional

from src.models.execution import (
    ExecutionRequest,
    ExecutionResponse,
    ExecutionDetailResponse,
    RepairExecutionRequest,
    RepairExecutionResponse,
    RollbackRequest,
    RollbackResponse
)
from src.services.execution_engine import ExecutionEngine
from src.services.planning_engine import PlanningEngine
from src.core.deps import get_tenant_id

router = APIRouter()


def get_db(request: Request) -> AsyncIOMotorDatabase:
    """获取数据库实例"""
    return request.app.mongodb


def get_engine(request: Request) -> ExecutionEngine:
    """获取执行引擎实例"""
    db = request.app.mongodb
    mcp_registry = getattr(request.app, 'mcp_registry', None)
    return ExecutionEngine(db, mcp_registry)


def get_planning_engine(request: Request) -> PlanningEngine:
    return PlanningEngine(
        request.app.mongodb,
        getattr(request.app, 'mcp_registry', None),
        getattr(request.app, 'command_retriever', None)
    )


@router.post("/", response_model=ExecutionResponse)
async def execute_plan(
    request: ExecutionRequest,
    http_request: Request,
    tenant_id: int = Depends(get_tenant_id),
    engine: ExecutionEngine = Depends(get_engine)
):
    """
    执行计划

    Args:
        request: 执行请求，包含计划步骤列表
        http_request: HTTP 请求对象（用于提取认证令牌）
        tenant_id: 租户 ID（从认证上下文获取）
        engine: 执行引擎

    Returns:
        执行响应，包含 execution_id 和初始状态

    Raises:
        HTTPException: 计划无效或执行失败
    """
    # Validate plan is not empty
    if not request.plan or len(request.plan) == 0:
        raise HTTPException(
            status_code=400,
            detail="Plan cannot be empty. Please ensure a valid plan is provided before execution."
        )

    try:
        # 创建执行请求，tenant_id 通过依赖注入获取
        execution_request = ExecutionRequest(
            plan=request.plan,
            global_timeout=request.global_timeout,
            goal=request.goal,
            auth_token=request.auth_token
        )

        # 如果未提供 auth_token，从 HTTP 请求头中提取
        if not execution_request.auth_token:
            auth_header = http_request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                execution_request.auth_token = auth_header[7:]  # 移除 "Bearer " 前缀

        # 获取 user_id（从认证上下文）
        # TODO: 从 Membership 认证中获取 user_id
        user_id = "system"  # 临时使用 system，实际应该从 JWT 中提取

        # 执行计划
        response = await engine.execute_plan(execution_request, tenant_id, user_id)

        return response

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@router.get("/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(
    execution_id: str,
    tenant_id: int = Depends(get_tenant_id),
    engine: ExecutionEngine = Depends(get_engine)
):
    """
    获取执行详情

    Args:
        execution_id: 执行记录 ID
        tenant_id: 租户 ID（用于权限验证）
        engine: 执行引擎

    Returns:
        执行详情，包含所有步骤的状态

    Raises:
        HTTPException: 执行记录不存在或无权限访问
    """
    # TODO: 添加租户权限验证

    execution = await engine.get_execution(execution_id)

    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    return execution


@router.post("/{execution_id}/rollback", response_model=RollbackResponse)
async def rollback_execution(
    execution_id: str,
    request: RollbackRequest,
    tenant_id: int = Depends(get_tenant_id),
    engine: ExecutionEngine = Depends(get_engine)
):
    """
    回滚执行

    从指定步骤开始，倒序回滚所有已成功的步骤

    Args:
        execution_id: 执行记录 ID
        request: 回滚请求，包含回滚起始步骤
        tenant_id: 租户 ID（用于权限验证）
        engine: 执行引擎

    Returns:
        回滚响应，包含回滚的步骤数量

    Raises:
        HTTPException: 执行记录不存在或回滚失败
    """
    # TODO: 添加租户权限验证

    # 获取 user_id
    user_id = "system"  # 临时使用 system，实际应该从 JWT 中提取

    try:
        response = await engine.rollback_execution(execution_id, request, user_id)
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(e)}")


@router.post("/{execution_id}/repair", response_model=RepairExecutionResponse)
async def repair_execution(
    execution_id: str,
    request: RepairExecutionRequest,
    http_request: Request,
    tenant_id: int = Depends(get_tenant_id),
    engine: ExecutionEngine = Depends(get_engine),
    planning_engine: PlanningEngine = Depends(get_planning_engine),
):
    execution = await engine.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    if not execution.repair_hint or not execution.repair_hint.recoverable:
        raise HTTPException(status_code=400, detail="This execution is not eligible for interactive repair")

    auth_token = request.auth_token
    if not auth_token:
        auth_header = http_request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            auth_token = auth_header[7:]

    repaired = await planning_engine.repair_plan(
        goal=request.goal,
        tenant_id=tenant_id,
        failed_plan=execution.steps,
        failure_summary=execution.repair_hint.summary,
        guidance=request.guidance,
        conversation_history=request.conversation_history,
        user_id="system",
        auth_token=auth_token,
    )

    return RepairExecutionResponse(
        confidence=repaired["confidence"],
        repairSummary=repaired["repair_summary"],
        repairPlanDescription=repaired["plan_description"],
        repairedPlan=repaired["plan"],
        sourceExecutionId=execution_id,
    )


@router.get("/")
async def list_executions(
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None
):
    """
    列出执行记录

    Args:
        tenant_id: 租户 ID
        db: 数据库实例
        skip: 跳过的记录数
        limit: 返回的记录数
        status: 可选的状态过滤

    Returns:
        执行记录列表
    """
    query = {"tenant_id": tenant_id}
    if status:
        query["status"] = status

    cursor = db["executions"].find(query).skip(skip).limit(limit).sort("started_at", -1)
    results = []
    async for doc in cursor:
        # 返回简要信息，不包含步骤详情
        results.append({
            "execution_id": str(doc["_id"]),
            "status": doc.get("status"),
            "total_steps": doc.get("total_steps"),
            "completed_steps": doc.get("completed_steps", 0),
            "failed_steps": doc.get("failed_steps", 0),
            "started_at": doc.get("started_at"),
            "completed_at": doc.get("completed_at")
        })

    return results
