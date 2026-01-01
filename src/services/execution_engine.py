import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.models.execution import (
    ExecutionRecord,
    ExecutionStatus,
    StepExecution,
    StepStatus,
    ExecutionRequest,
    ExecutionResponse,
    ExecutionDetailResponse,
    RollbackRequest,
    RollbackResponse
)
from src.services.execution_repository import ExecutionRepository
from src.services.http_client import HTTPClient
from src.services.membership_client import MembershipClient
from src.core.config import settings

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """执行引擎 - 负责执行计划并管理步骤"""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        初始化执行引擎

        Args:
            db: MongoDB 异步数据库实例
        """
        self.db = db
        self.repository = ExecutionRepository(db)

    async def execute_plan(
        self,
        request: ExecutionRequest,
        tenant_id: int,
        user_id: str
    ) -> ExecutionResponse:
        """
        执行计划

        Args:
            request: 执行请求
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            执行响应
        """
        # 生成 plan_id（用于追踪）
        plan_id = f"plan_{datetime.utcnow().timestamp()}"

        # 创建执行记录
        execution = await self.repository.create_execution(
            tenant_id=tenant_id,
            plan_id=plan_id,
            plan=request.plan,
            global_timeout=request.global_timeout,
            created_by=user_id
        )

        # 写入审计日志
        await self.repository.write_audit_log(
            tenant_id=tenant_id,
            category="task_execution",
            action="plan_started",
            resource=f"execution:{execution.id}",
            subject=user_id,
            payload={
                "plan_id": plan_id,
                "total_steps": len(request.plan),
                "global_timeout": request.global_timeout
            }
        )

        # 异步执行计划（不阻塞响应）
        asyncio.create_task(
            self._execute_plan_async(
                execution_id=execution.id,
                plan=request.plan,
                tenant_id=tenant_id,
                auth_token=request.auth_token,
                user_id=user_id,
                global_timeout=request.global_timeout
            )
        )

        return ExecutionResponse(
            execution_id=execution.id,
            status=ExecutionStatus.RUNNING,
            total_steps=len(request.plan),
            started_at=execution.started_at
        )

    async def _execute_plan_async(
        self,
        execution_id: str,
        plan: List[Dict[str, Any]],
        tenant_id: int,
        auth_token: str,
        user_id: str,
        global_timeout: int
    ):
        """
        异步执行计划

        Args:
            execution_id: 执行记录 ID
            plan: 计划步骤列表
            tenant_id: 租户 ID
            auth_token: JWT token
            user_id: 用户 ID
            global_timeout: 全局超时时间
        """
        step_results: List[StepExecution] = []

        try:
            # 创建所有步骤记录
            for idx, step_def in enumerate(plan, 1):
                step = await self.repository.create_step(
                    execution_id=execution_id,
                    step_number=idx,
                    command=step_def.get("command", ""),
                    description=step_def.get("description", ""),
                    timeout=step_def.get("timeout", 30)
                )
                step_results.append(step)

            # 全局超时控制 (Python 3.9 compatible)
            await asyncio.wait_for(
                self._execute_all_steps(
                    execution_id=execution_id,
                    plan=plan,
                    step_results=step_results,
                    tenant_id=tenant_id,
                    auth_token=auth_token
                ),
                timeout=global_timeout
            )

            # 所有步骤完成，更新执行状态
            failed_count = sum(1 for s in step_results if s.status == StepStatus.FAILED)

            if failed_count == 0:
                final_status = ExecutionStatus.COMPLETED
            elif failed_count < len(step_results):
                final_status = ExecutionStatus.PARTIAL_FAILED
            else:
                final_status = ExecutionStatus.FAILED

            await self.repository.update_execution(
                execution_id=execution_id,
                status=final_status,
                completed_at=datetime.utcnow(),
                completed_steps=len(step_results),
                failed_steps=failed_count
            )

        except asyncio.TimeoutError:
            logger.error(f"Execution {execution_id} timed out after {global_timeout}s")
            await self.repository.update_execution(
                execution_id=execution_id,
                status=ExecutionStatus.TIMEOUT,
                completed_at=datetime.utcnow(),
                error_message=f"Execution timed out after {global_timeout}s"
            )

        except Exception as e:
            logger.error(f"Execution {execution_id} failed: {e}")
            await self.repository.update_execution(
                execution_id=execution_id,
                status=ExecutionStatus.FAILED,
                completed_at=datetime.utcnow(),
                error_message=str(e)
            )

    async def _execute_all_steps(
        self,
        execution_id: str,
        plan: List[Dict[str, Any]],
        step_results: List[StepExecution],
        tenant_id: int,
        auth_token: str
    ):
        """
        执行所有步骤

        Args:
            execution_id: 执行记录 ID
            plan: 计划步骤列表
            step_results: 步骤执行记录列表
            tenant_id: 租户 ID
            auth_token: JWT token
        """
        # 顺序执行每个步骤
        for idx, step in enumerate(step_results):
            # 检查是否应该跳过此步骤（基于依赖检查）
            should_skip = self._should_skip_step(idx, step_results, plan)

            if should_skip:
                # 跳过此步骤
                await self.repository.update_step(
                    step_id=step.id,
                    status=StepStatus.SKIPPED,
                    error_message="Skipped due to failed dependency",
                    completed_at=datetime.utcnow()
                )

                # 写入审计日志
                await self.repository.write_audit_log(
                    tenant_id=tenant_id,
                    category="task_execution",
                    action="step_skipped",
                    resource=f"execution:{step.execution_id}:step:{step.step_number}",
                    subject=auth_token,
                    payload={
                        "step_number": step.step_number,
                        "command": step.command,
                        "reason": "dependency_failed"
                    }
                )
                logger.info(f"Step {step.step_number} skipped due to failed dependency")
                continue

            # 执行步骤
            await self._execute_step(
                step=step,
                plan=plan,
                step_results=step_results,
                tenant_id=tenant_id,
                auth_token=auth_token
            )

    def _should_skip_step(
        self,
        current_idx: int,
        step_results: List[StepExecution],
        plan: List[Dict[str, Any]]
    ) -> bool:
        """
        检查步骤是否应该被跳过（基于依赖检查）

        Args:
            current_idx: 当前步骤的索引
            step_results: 步骤执行记录列表
            plan: 计划步骤列表

        Returns:
            True 如果步骤应该被跳过，False 否则
        """
        # 第一个步骤永远不跳过
        if current_idx == 0:
            return False

        # 检查前面的步骤中是否有失败的
        has_failed_dependency = False
        for i in range(current_idx):
            prev_step = step_results[i]
            if prev_step.status == StepStatus.FAILED:
                has_failed_dependency = True
                break

        # 如果没有失败的依赖，不跳过
        if not has_failed_dependency:
            return False

        # 检查当前步骤是否依赖前面的步骤
        # 通过检查参数中是否包含 JSONPath 引用来判断
        current_step_def = plan[current_idx]
        params = current_step_def.get("params", {})

        # 递归检查参数中是否包含 JSONPath 引用（以 $ 开头）
        def contains_jsonpath(obj):
            if isinstance(obj, str):
                return obj.startswith("$")
            elif isinstance(obj, dict):
                return any(contains_jsonpath(v) for v in obj.values())
            elif isinstance(obj, list):
                return any(contains_jsonpath(item) for item in obj)
            return False

        has_dependency = contains_jsonpath(params)

        # 如果有失败的依赖且当前步骤有 JSONPath 引用，则跳过
        return has_dependency

    async def _execute_step(
        self,
        step: StepExecution,
        plan: List[Dict[str, Any]],
        step_results: List[StepExecution],
        tenant_id: int,
        auth_token: str
    ):
        """
        执行单个步骤

        Args:
            step: 步骤执行记录
            plan: 原始计划
            step_results: 已执行的步骤结果
            tenant_id: 租户 ID
            auth_token: JWT token
        """
        step_def = plan[step.step_number - 1]  # 获取步骤定义

        # 更新步骤状态为运行中
        await self.repository.update_step(
            step_id=step.id,
            status=StepStatus.RUNNING,
            started_at=datetime.utcnow()
        )

        # 解析参数（解析 JSONPath 引用）
        resolved_params = self._resolve_params(
            params=step_def.get("params", {}),
            step_results=step_results
        )

        # 记录请求数据
        await self.repository.update_step(
            step_id=step.id,
            request_data=resolved_params
        )

        # 执行步骤并处理结果
        client = None
        try:
            # 特殊处理用户创建命令
            response_data = None
            if step.command.startswith("POST /v2/members"):
                # 用户创建命令 - 使用 MembershipClient
                client = MembershipClient()
                user_data = resolved_params.get("body", {})
                response_data = await client.create_member(
                    tenant_id=tenant_id,
                    username=user_data.get("username"),
                    email=user_data.get("email"),
                    password=user_data.get("password"),
                    is_virtual=user_data.get("is_virtual", True),
                    auth_token=auth_token
                )
                logger.info(f"User created successfully: {user_data.get('username')}")
            else:
                # 普通 HTTP 请求 - 使用 HTTPClient
                client = HTTPClient()
                response_data = await client.execute(
                    command=step.command,
                    params=resolved_params,
                    auth_token=auth_token,
                    tenant_id=tenant_id,
                    timeout=step.timeout
                )

            # 记录响应数据
            if response_data is not None:
                await self.repository.update_step(
                    step_id=step.id,
                    status=StepStatus.SUCCESS,
                    response_data=response_data,
                    completed_at=datetime.utcnow()
                )

                # 写入审计日志
                await self.repository.write_audit_log(
                    tenant_id=tenant_id,
                    category="task_execution",
                    action="step_completed",
                    resource=f"execution:{step.execution_id}:step:{step.step_number}",
                    subject=auth_token,  # 使用 token 作为主体标识
                    payload={
                        "step_number": step.step_number,
                        "command": step.command,
                        "success": True
                    }
                )

        except Exception as e:
            logger.error(f"Step {step.step_number} failed: {e}")

            # 记录错误
            await self.repository.update_step(
                step_id=step.id,
                status=StepStatus.FAILED,
                error_message=str(e),
                completed_at=datetime.utcnow()
            )

            # 写入审计日志
            await self.repository.write_audit_log(
                tenant_id=tenant_id,
                category="task_execution",
                action="step_failed",
                resource=f"execution:{step.execution_id}:step:{step.step_number}",
                subject=auth_token,
                payload={
                    "step_number": step.step_number,
                    "command": step.command,
                    "error": str(e)
                }
            )
            raise

        finally:
            # 清理资源
            if client is not None:
                await client.close()

    def _resolve_params(
        self,
        params: Dict[str, Any],
        step_results: List[StepExecution]
    ) -> Dict[str, Any]:
        """
        解析参数中的 JSONPath 引用

        Args:
            params: 原始参数
            step_results: 已执行的步骤结果

        Returns:
            解析后的参数
        """
        resolved = params.copy()

        # 递归解析所有字符串值
        def resolve_value(value: Any) -> Any:
            if isinstance(value, str):
                # 检测 JSONPath 引用：$.steps[N].response.body.*
                if value.startswith("$.steps[") and "].response" in value:
                    return self._extract_from_jsonpath(value, step_results)
                return value
            elif isinstance(value, dict):
                return {k: resolve_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [resolve_value(item) for item in value]
            return value

        return resolve_value(resolved)

    def _extract_from_jsonpath(
        self,
        jsonpath: str,
        step_results: List[StepExecution]
    ) -> Any:
        """
        从 JSONPath 提取值

        支持格式：$.steps[N].response.body.field

        Args:
            jsonpath: JSONPath 表达式
            step_results: 步骤执行结果

        Returns:
            提取的值
        """
        try:
            # 解析步骤索引
            start_idx = jsonpath.index("[") + 1
            end_idx = jsonpath.index("]")
            step_idx = int(jsonpath[start_idx:end_idx])

            # 获取对应步骤的结果
            if step_idx >= len(step_results):
                logger.error(f"Invalid step index: {step_idx}")
                return None

            step = step_results[step_idx]
            if not step.response_data:
                logger.error(f"Step {step_idx} has no response data")
                return None

            # 解析路径：response.body.field
            path_parts = jsonpath[end_idx + 1:].strip(".").split(".")

            current = step.response_data
            for part in path_parts:
                if isinstance(current, dict):
                    current = current.get(part)
                elif isinstance(current, list) and part.isdigit():
                    current = current[int(part)]
                else:
                    logger.error(f"Cannot access path: {part}")
                    return None

            return current

        except Exception as e:
            logger.error(f"Failed to parse JSONPath {jsonpath}: {e}")
            return None

    async def get_execution(self, execution_id: str) -> Optional[ExecutionDetailResponse]:
        """
        获取执行详情

        Args:
            execution_id: 执行记录 ID

        Returns:
            执行详情响应
        """
        execution = await self.repository.get_execution(execution_id)
        if not execution:
            return None

        steps = await self.repository.get_steps(execution_id)

        return ExecutionDetailResponse(
            execution_id=execution.id,
            status=execution.status,
            total_steps=execution.total_steps,
            completed_steps=execution.completed_steps,
            failed_steps=execution.failed_steps,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            error_message=execution.error_message,
            steps=[step.model_dump(by_alias=True) for step in steps]
        )

    async def rollback_execution(
        self,
        execution_id: str,
        request: RollbackRequest,
        user_id: str
    ) -> RollbackResponse:
        """
        回滚执行

        Args:
            execution_id: 执行记录 ID
            request: 回滚请求
            user_id: 用户 ID

        Returns:
            回滚响应
        """
        execution = await self.repository.get_execution(execution_id)
        if not execution:
            return RollbackResponse(
                status="error",
                rolled_back_steps=0,
                message="Execution not found"
            )

        # 获取所有步骤
        all_steps = await self.repository.get_steps(execution_id)

        # 过滤需要回滚的步骤（从指定步骤开始，倒序回滚）
        steps_to_rollback = [
            s for s in all_steps
            if s.step_number >= request.rollback_from_step
            and s.status == StepStatus.SUCCESS
            and s.rollback_command
        ]

        # 按步骤编号倒序排列
        steps_to_rollback.sort(key=lambda x: x.step_number, reverse=True)

        http_client = HTTPClient()
        rolled_back_count = 0

        try:
            for step in steps_to_rollback:
                try:
                    # 执行回滚命令
                    await http_client.execute(
                        command=step.rollback_command,
                        params={},  # 回滚命令通常不需要参数
                        auth_token=user_id,  # 使用 user_id 作为 token
                        tenant_id=execution.tenant_id,
                        timeout=30
                    )

                    # 更新回滚状态
                    await self.repository.update_step(
                        step_id=step.id,
                        rollback_status="success"
                    )

                    rolled_back_count += 1

                    # 写入审计日志
                    await self.repository.write_audit_log(
                        tenant_id=execution.tenant_id,
                        category="task_execution",
                        action="step_rolled_back",
                        resource=f"execution:{execution_id}:step:{step.step_number}",
                        subject=user_id,
                        payload={
                            "step_number": step.step_number,
                            "rollback_command": step.rollback_command
                        }
                    )

                except Exception as e:
                    logger.error(f"Rollback step {step.step_number} failed: {e}")
                    await self.repository.update_step(
                        step_id=step.id,
                        rollback_status="failed"
                    )

            # 更新执行状态
            await self.repository.update_execution(
                execution_id=execution_id,
                status=ExecutionStatus.ROLLBACK
            )

            return RollbackResponse(
                status="success",
                rolled_back_steps=rolled_back_count,
                message=f"Successfully rolled back {rolled_back_count} steps"
            )

        except Exception as e:
            logger.error(f"Rollback execution {execution_id} failed: {e}")
            return RollbackResponse(
                status="error",
                rolled_back_steps=rolled_back_count,
                message=f"Rollback failed: {str(e)}"
            )

        finally:
            await http_client.close()