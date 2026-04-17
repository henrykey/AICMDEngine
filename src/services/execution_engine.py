import logging
import asyncio
import json
import re
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
    UserExecutionSummary,
    RepairHint,
    RollbackRequest,
    RollbackResponse
)
from src.services.execution_repository import ExecutionRepository
from src.services.http_client import HTTPClient
from src.services.membership_client import MembershipClient
from src.core.config import settings
from src.mcp.registry import MCPRegistry

logger = logging.getLogger(__name__)


def _detect_language(text: str) -> str:
    """Detect if text is primarily Chinese or English.

    Returns 'zh' if Chinese characters dominate, 'en' otherwise.
    """
    if not text:
        return 'en'
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return 'zh' if chinese_chars > len(text) * 0.3 else 'en'


class BilingualMessages:
    """Bilingual message templates for execution-related user-facing responses."""

    MESSAGES = {
        'zh': {
            'detail_success': '已完成 {succeeded}/{total} 个步骤',
            'detail_failed': '{failed} 个步骤失败',
            'detail_skipped': '{skipped} 个步骤已跳过',
            'detail_running': '系统仍在执行中',
            'completed_headline': '任务已完成',
            'completed_summary': '系统已经完成这次请求，正式结果会以自然语言为主，内部步骤已放到调试详情中。',
            'completed_debug': '如需查看具体命令、参数和原始响应，可展开调试详情。',
            'running_headline': '任务执行中',
            'running_summary': '系统正在按规划执行这次请求，界面会持续更新当前进度。',
            'running_next': '等待执行完成后查看最终结果。',
            'running_debug': '调试详情中可查看当前步骤状态和原始返回。',
            'failed_headline': '任务未完整完成',
            'failed_summary': '执行过程中出现异常，系统暂时没有完成这次请求。',
            'failed_next': '可重试本次请求；如需排查原因，请展开调试详情。',
            'failed_debug': '调试详情中保留了失败步骤、错误信息和原始响应。',
            'updated_headline': '任务状态已更新',
            'updated_summary': '系统已更新这次请求的执行状态。',
            'updated_debug': '调试详情中可查看完整步骤轨迹。',
            'repair_missing_dep_summary': '当前计划缺少中间依赖解析步骤，导致后续命令没有拿到必需参数。',
            'repair_missing_dep_action': '请继续教系统如何从上一步结果中提取正确参数，然后重新规划执行。',
            'repair_missing_dep_prompt': '请告诉我：应该怎样从前一步结果中取得后续命令需要的参数。例如是先从成员列表中按 username/fullName 匹配，再提取 member_id。',
            'repair_jsonpath_summary': '当前计划引用了前一步结果，但结果提取路径或中间步骤设计不正确。',
            'repair_jsonpath_action': '请补充更合适的中间步骤或更明确的结果提取方式。',
            'repair_jsonpath_prompt': '请告诉我应如何从已有结果中更准确地定位目标对象或提取字段。',
            'repair_business_action': '这是已确认的业务结果，不需要继续技术修复。',
            'repair_unknown_summary': '执行失败，暂时无法自动修复。',
            'repair_unknown_action': '请查看调试详情后决定是否人工提供新的求解思路。',
        },
        'en': {
            'detail_success': 'Completed {succeeded}/{total} steps',
            'detail_failed': '{failed} steps failed',
            'detail_skipped': '{skipped} steps skipped',
            'detail_running': 'System is still executing',
            'completed_headline': 'Task completed',
            'completed_summary': 'The system has completed this request. Results are returned in natural language; internal steps are in debug details.',
            'completed_debug': 'Expand debug details to view specific commands, parameters, and raw responses.',
            'running_headline': 'Task executing',
            'running_summary': 'The system is executing the plan. Progress will update continuously.',
            'running_next': 'Wait for execution to complete and view final results.',
            'running_debug': 'Debug details show current step status and raw responses.',
            'failed_headline': 'Task not fully completed',
            'failed_summary': 'An exception occurred during execution. The system has not completed this request yet.',
            'failed_next': 'You can retry this request; expand debug details to investigate.',
            'failed_debug': 'Debug details contain failed steps, error messages, and raw responses.',
            'updated_headline': 'Task status updated',
            'updated_summary': 'The system has updated the execution status for this request.',
            'updated_debug': 'Debug details show complete step trajectory.',
            'repair_missing_dep_summary': 'The plan is missing intermediate dependency resolution steps, so subsequent commands did not receive required parameters.',
            'repair_missing_dep_action': 'Please teach the system how to extract correct parameters from previous step results, then replan and execute.',
            'repair_missing_dep_prompt': 'Tell me: How should I obtain parameters needed by subsequent commands from previous step results? For example, match by username/fullName from member list first, then extract member_id.',
            'repair_jsonpath_summary': 'The plan references previous step results, but the extraction path or intermediate step design is incorrect.',
            'repair_jsonpath_action': 'Please add more appropriate intermediate steps or a clearer extraction method.',
            'repair_jsonpath_prompt': 'Tell me how to more accurately locate target objects or extract fields from existing results.',
            'repair_business_action': 'This is a confirmed business outcome; no further technical repair is needed.',
            'repair_unknown_summary': 'Execution failed; cannot auto-repair for now.',
            'repair_unknown_action': 'View debug details and decide whether to provide new manual guidance.',
        },
    }

    @classmethod
    def get(cls, language: str, key: str, **kwargs) -> str:
        """Get a message in the specified language with optional formatting."""
        msg = cls.MESSAGES.get(language, cls.MESSAGES['en']).get(key, '')
        if kwargs and msg:
            try:
                return msg.format(**kwargs)
            except (KeyError, ValueError):
                return msg
        return msg


class ExecutionEngine:
    """执行引擎 - 负责执行计划并管理步骤"""

    def __init__(self, db: AsyncIOMotorDatabase, mcp_registry: Optional[MCPRegistry] = None):
        """
        初始化执行引擎

        Args:
            db: MongoDB 异步数据库实例
            mcp_registry: MCP registry for executing MCP commands (optional)
        """
        self.db = db
        self.repository = ExecutionRepository(db)
        self.mcp_registry = mcp_registry

    def _extract_member_candidates(self, response_data: Any) -> List[Dict[str, Any]]:
        if isinstance(response_data, dict):
            for key in ("data", "members", "items", "results"):
                value = response_data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            return [response_data] if any(key in response_data for key in ("id", "fullName", "username")) else []
        if isinstance(response_data, list):
            return [item for item in response_data if isinstance(item, dict)]
        return []

    async def _execute_internal_lookup_member_by_name(
        self,
        step: StepExecution,
        resolved_params: Dict[str, Any],
        step_results: List[StepExecution],
    ) -> tuple[Dict[str, Any], str]:
        member_name = str(resolved_params.get("member_name", "")).strip()
        source_step_number = int(resolved_params.get("source_step", 0) or 0)
        if not member_name:
            raise ValueError("Internal lookup failed: member_name is required")
        if source_step_number <= 0 or source_step_number > len(step_results):
            raise ValueError("Internal lookup failed: source_step is invalid")

        source_step = step_results[source_step_number - 1]
        candidates = self._extract_member_candidates(source_step.response_data)
        exact_matches = [
            item for item in candidates
            if str(item.get("fullName", "")).strip() == member_name
        ]
        if not exact_matches:
            exact_matches = [
                item for item in candidates
                if str(item.get("username", "")).strip() == member_name
                or str(item.get("name", "")).strip() == member_name
            ]

        if len(exact_matches) == 1:
            member = exact_matches[0]
            member_id = member.get("id")
            if member_id is None:
                raise ValueError(f"已找到成员“{member_name}”，但结果中没有可用的 id。")
            content = f"已定位成员“{member_name}”的ID：{member_id}"
            return member, content

        if len(exact_matches) == 0:
            raise ValueError(f"未找到成员“{member_name}”。请确认名称是否正确，或先创建该成员。")

        raise ValueError(f"找到多个名为“{member_name}”的成员，无法唯一确定目标。")

    def _friendly_execution_error(self, error_message: Optional[str], language: str = 'zh') -> Optional[str]:
        if not error_message:
            return None
        lowered = error_message.lower()
        if "could not resolve" in lowered or "failed to extract values" in lowered:
            return BilingualMessages.get(language, 'repair_unknown_summary')
        if "missing 1 required positional argument" in lowered or "invalid parameters for tool" in lowered:
            return BilingualMessages.get(language, 'repair_missing_dep_summary')
        if "timed out" in lowered:
            return BilingualMessages.get(language, 'failed_summary')
        return BilingualMessages.get(language, 'failed_summary')

    def _build_repair_hint(
        self,
        execution: ExecutionRecord,
        steps: List[StepExecution],
    ) -> Optional[RepairHint]:
        failed_steps = [step for step in steps if step.status == StepStatus.FAILED]
        if not failed_steps:
            return None

        failed_step = failed_steps[-1]
        error_text = failed_step.error_message or execution.error_message or ""
        lowered = error_text.lower()

        # Detect language from error text or goal
        language = _detect_language(execution.original_goal or error_text)

        if "missing 1 required positional argument" in lowered or "invalid parameters for tool" in lowered:
            return RepairHint(
                recoverable=True,
                category="missing_intermediate_dependency",
                summary=BilingualMessages.get(language, 'repair_missing_dep_summary'),
                suggestedAction=BilingualMessages.get(language, 'repair_missing_dep_action'),
                coachPrompt=BilingualMessages.get(language, 'repair_missing_dep_prompt'),
            )

        if "could not resolve" in lowered or "failed to extract values" in lowered:
            return RepairHint(
                recoverable=True,
                category="jsonpath_or_result_extraction_failure",
                summary=BilingualMessages.get(language, 'repair_jsonpath_summary'),
                suggestedAction=BilingualMessages.get(language, 'repair_jsonpath_action'),
                coachPrompt=BilingualMessages.get(language, 'repair_jsonpath_prompt'),
            )

        if "未找到成员" in error_text or "找到多个名为" in error_text:
            return RepairHint(
                recoverable=False,
                category="business_outcome_confirmed",
                summary=error_text,
                suggestedAction=BilingualMessages.get(language, 'repair_business_action'),
                coachPrompt=None,
            )

        return RepairHint(
            recoverable=False,
            category="unknown_execution_failure",
            summary=self._friendly_execution_error(error_text, language) or BilingualMessages.get(language, 'repair_unknown_summary'),
            suggestedAction=BilingualMessages.get(language, 'repair_unknown_action'),
            coachPrompt=None,
        )

    def _build_execution_user_summary(
        self,
        execution: ExecutionRecord,
        steps: List[StepExecution],
    ) -> UserExecutionSummary:
        total = len(steps)
        succeeded = sum(1 for step in steps if step.status == StepStatus.SUCCESS)
        failed = sum(1 for step in steps if step.status == StepStatus.FAILED)
        skipped = sum(1 for step in steps if step.status == StepStatus.SKIPPED)
        running = sum(1 for step in steps if step.status == StepStatus.RUNNING)

        # Detect language from original goal
        goal_text = execution.original_goal or ""
        logger.info(f"[Bilingual] _build_execution_user_summary: original_goal={goal_text[:100] if goal_text else 'EMPTY'}")
        language = _detect_language(goal_text)
        logger.info(f"[Bilingual] detected language: {language} (goal_text len={len(goal_text)})")

        detail_lines = []
        if total:
            detail_lines.append(BilingualMessages.get(language, 'detail_success', succeeded=succeeded, total=total))
        if failed:
            detail_lines.append(BilingualMessages.get(language, 'detail_failed', failed=failed))
        if skipped:
            detail_lines.append(BilingualMessages.get(language, 'detail_skipped', skipped=skipped))
        if running:
            detail_lines.append(BilingualMessages.get(language, 'detail_running'))

        if execution.status == ExecutionStatus.COMPLETED:
            return UserExecutionSummary(
                headline=BilingualMessages.get(language, 'completed_headline'),
                summary=BilingualMessages.get(language, 'completed_summary'),
                statusLabel="completed",
                nextAction=None,
                detailLines=detail_lines,
                debugHint=BilingualMessages.get(language, 'completed_debug'),
            )

        if execution.status == ExecutionStatus.RUNNING:
            return UserExecutionSummary(
                headline=BilingualMessages.get(language, 'running_headline'),
                summary=BilingualMessages.get(language, 'running_summary'),
                statusLabel="running",
                nextAction=BilingualMessages.get(language, 'running_next'),
                detailLines=detail_lines,
                debugHint=BilingualMessages.get(language, 'running_debug'),
            )

        if execution.status in {ExecutionStatus.FAILED, ExecutionStatus.PARTIAL_FAILED, ExecutionStatus.TIMEOUT}:
            return UserExecutionSummary(
                headline=BilingualMessages.get(language, 'failed_headline'),
                summary=self._friendly_execution_error(execution.error_message, language) or BilingualMessages.get(language, 'failed_summary'),
                statusLabel="failed",
                nextAction=BilingualMessages.get(language, 'failed_next'),
                detailLines=detail_lines,
                debugHint=BilingualMessages.get(language, 'failed_debug'),
            )

        return UserExecutionSummary(
            headline=BilingualMessages.get(language, 'updated_headline'),
            summary=BilingualMessages.get(language, 'updated_summary'),
            statusLabel=str(execution.status),
            nextAction=None,
            detailLines=detail_lines,
            debugHint=BilingualMessages.get(language, 'updated_debug'),
        )

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
            created_by=user_id,
            original_goal=getattr(request, "goal", None),
        )
        logger.info(f"[Bilingual] Created execution {execution.id} with original_goal: {execution.original_goal[:50] if execution.original_goal else 'EMPTY'}...")

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

        # 检查未解析的 JSONPath 引用。
        # 注意：params 中的 None 可能是合法的可选参数（例如 parent_id=None），
        # 只有当 None 是由 JSONPath 解析失败导致时才应判定为错误。
        unresolved_fields = self._find_unresolved_fields(resolved_params, step_def.get('params', {}))
        if unresolved_fields:
            error_msg = f"Step {step.step_number} failed to extract values from previous steps. Could not resolve: {unresolved_fields}. This usually means a previous step did not return the expected data structure."
            logger.error(error_msg)
            logger.debug(f"Original params: {step_def.get('params', {})}, Resolved params: {resolved_params}")

            # 更新内存中的步骤对象
            step.status = StepStatus.FAILED
            step.error_message = error_msg
            step.completed_at = datetime.utcnow()

            # 更新数据库
            await self.repository.update_step(
                step_id=step.id,
                status=StepStatus.FAILED,
                error_message=error_msg,
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
                    "error": "Unresolved JSONPath references"
                }
            )
            raise ValueError(error_msg)

        # 记录请求数据
        await self.repository.update_step(
            step_id=step.id,
            request_data=resolved_params
        )

        # 执行步骤并处理结果
        client = None
        try:
            response_data = None
            result_content = None  # Human-readable result content

            if step.command == "INTERNAL.lookup_member_by_name":
                response_data, result_content = await self._execute_internal_lookup_member_by_name(
                    step=step,
                    resolved_params=resolved_params,
                    step_results=step_results,
                )
            # 优先使用 MCP 命令执行
            elif self.mcp_registry:
                # 尝试从命令字符串中提取 MCP 名称和工具名称
                mcp_name, tool_name = self._parse_command_to_mcp(step.command)

                if mcp_name and tool_name:
                    # 使用 MCP 执行命令
                    logger.info(f"Executing MCP command: {mcp_name}.{tool_name}")
                    
                    # Extract and flatten parameters for MCP tools
                    # The planning engine puts parameters in body/query/path/headers structure,
                    # but MCP tools expect flat parameters at the top level
                    mcp_params = self._flatten_mcp_params(resolved_params)
                    mcp_params = self._normalize_mcp_params(mcp_name, tool_name, mcp_params)
                    
                    # Add auth_token and tenant_id to MCP command execution
                    mcp_params["auth_token"] = auth_token
                    mcp_params["tenant_id"] = tenant_id
                    
                    logger.debug(f"MCP params after flattening: {mcp_params}")

                    missing_required_msg = self._validate_required_mcp_params(mcp_name, tool_name, mcp_params)
                    if missing_required_msg:
                        logger.error(missing_required_msg)
                        raise ValueError(missing_required_msg)
                    
                    result = await self.mcp_registry.execute_command(
                        mcp_name=mcp_name,
                        tool_name=tool_name,
                        **mcp_params
                    )

                    if result.is_error:
                        error_msg = f"MCP command failed: {result.content}"
                        logger.error(error_msg)
                        raise ValueError(error_msg)

                    response_data = result.data if result.data else result.content
                    if response_data is None:
                        response_data = {"success": True}

                    # Capture human-readable content from MCP tool result
                    result_content = result.content
                    logger.info(f"MCP {mcp_name}.{tool_name} executed: result.content={result.content[:100] if result.content and len(result.content) > 100 else result.content}, result.data={type(result.data).__name__ if result.data else None}")

                    logger.info(f"MCP command executed successfully: {mcp_name}.{tool_name}")
                else:
                    # 回退到 HTTP 客户端
                    logger.warning(f"MCP not found for command: {step.command}, falling back to HTTP")
                    client = HTTPClient(base_url=settings.membership_service_url, membership_url=settings.membership_service_url)
                    response_data = await client.execute(
                        command=step.command,
                        params=resolved_params,
                        auth_token=auth_token,
                        tenant_id=tenant_id,
                        timeout=step.timeout
                    )
            else:
                # 如果没有 MCP registry，直接使用 HTTP 客户端
                client = HTTPClient(base_url=settings.membership_service_url, membership_url=settings.membership_service_url)
                response_data = await client.execute(
                    command=step.command,
                    params=resolved_params,
                    auth_token=auth_token,
                    tenant_id=tenant_id,
                    timeout=step.timeout
                )

            # 记录响应数据
            if response_data is not None:
                # 更新内存中的步骤对象，这样后续步骤可以访问响应数据
                step.response_data = response_data
                if result_content:
                    step.result_content = result_content
                    logger.info(f"Step {step.step_number} result_content: {result_content[:200] if len(result_content) > 200 else result_content}")
                else:
                    logger.warning(f"Step {step.step_number} has no result_content, response_data keys: {list(response_data.keys()) if isinstance(response_data, dict) else type(response_data)}")
                step.status = StepStatus.SUCCESS
                step.completed_at = datetime.utcnow()

                # 同时更新数据库
                await self.repository.update_step(
                    step_id=step.id,
                    status=StepStatus.SUCCESS,
                    response_data=response_data,
                    result_content=result_content,
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

            # 更新内存中的步骤对象
            step.status = StepStatus.FAILED
            step.error_message = str(e)
            step.completed_at = datetime.utcnow()

            # 记录错误到数据库
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

    def _contains_none_values(self, obj: Any) -> bool:
        """
        检查对象中是否包含 None 值（表示未解析的引用）

        Args:
            obj: 要检查的对象

        Returns:
            如果包含 None 值，返回 True
        """
        if obj is None:
            return True
        elif isinstance(obj, dict):
            return any(self._contains_none_values(v) for v in obj.values())
        elif isinstance(obj, list):
            return any(self._contains_none_values(item) for item in obj)
        return False

    def _apply_jsonpath_filter(self, items: List[Any], filter_expr: str) -> Optional[Any]:
        """
        应用 JSONPath 过滤器表达式到列表

        支持格式：
        - @.name == 'value'
        - @.id == 123
        - @.field != 'value'

        Args:
            items: 要过滤的项目列表
            filter_expr: 过滤表达式，例如 "@.name == 'IBC-AI'"

        Returns:
            过滤后的第一个匹配项，或 None
        """
        import re
        
        # 解析过滤表达式
        # 支持格式：@.field == 'string' 或 @.field == number
        match = re.match(r"@\.(\w+)\s*(==|!=|>|<|>=|<=)\s*['\"]?([^'\"]*)['\"]?", filter_expr)
        
        if not match:
            logger.warning(f"Cannot parse JSONPath filter: {filter_expr}")
            return None
        
        field_name = match.group(1)
        operator = match.group(2)
        value = match.group(3)
        
        # 尝试将值转换为数字
        try:
            value = int(value)
        except (ValueError, TypeError):
            try:
                value = float(value)
            except (ValueError, TypeError):
                pass  # 保持为字符串
        
        # 应用过滤器
        for item in items:
            if isinstance(item, dict):
                item_value = item.get(field_name)
                
                if operator == "==":
                    if item_value == value:
                        return item
                elif operator == "!=":
                    if item_value != value:
                        return item
                elif operator == ">":
                    if item_value is not None and item_value > value:
                        return item
                elif operator == "<":
                    if item_value is not None and item_value < value:
                        return item
                elif operator == ">=":
                    if item_value is not None and item_value >= value:
                        return item
                elif operator == "<=":
                    if item_value is not None and item_value <= value:
                        return item
        
        return None

    def _parse_jsonpath_parts(self, path_str: str) -> List[str]:
        """
        解析 JSONPath 路径字符串，正确处理数组索引和过滤器

        Examples:
            "data[0].id" -> ["data", "[0]", "id"]
            "body.user.name" -> ["body", "user", "name"]
            "items[0].fields[1].value" -> ["items", "[0]", "fields", "[1]", "value"]
            "data[?(@.name == 'IBC-AI')].id" -> ["data", "[?(@.name == 'IBC-AI')]", "id"]

        Args:
            path_str: 路径字符串

        Returns:
            路径部分列表
        """
        import re
        parts = []
        # 使用正则表达式分割：支持字段名、[数字]、和过滤器 [?(...)]
        # 匹配模式：字段名或 [...]（包括 [0]、[?(...)] 等）
        pattern = r'(\w+|\[[^\]]*\])'
        matches = re.findall(pattern, path_str)
        return matches

    def _find_unresolved_fields(self, resolved: Any, original: Any, path: str = "") -> List[str]:
        """
        找出哪些字段无法解析（值为 None）

        Args:
            resolved: 解析后的参数
            original: 原始参数
            path: 当前路径（用于递归）

        Returns:
            无法解析的字段列表
        """
        unresolved = []

        if isinstance(resolved, dict) and isinstance(original, dict):
            for key, value in resolved.items():
                current_path = f"{path}.{key}" if path else key
                if value is None and original.get(key) is not None:
                    # 这个字段在原始参数中有值，但解析后变成了 None
                    unresolved.append(f"{current_path} (original: {original.get(key)})")
                elif isinstance(value, (dict, list)):
                    unresolved.extend(self._find_unresolved_fields(value, original.get(key, {}), current_path))
        elif isinstance(resolved, list) and isinstance(original, list):
            for i, (r_item, o_item) in enumerate(zip(resolved, original)):
                current_path = f"{path}[{i}]"
                unresolved.extend(self._find_unresolved_fields(r_item, o_item, current_path))

        return unresolved

    def _resolve_params(
        self,
        params: Dict[str, Any],
        step_results: List[StepExecution],
        response_schemas: Dict[int, Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        解析参数中的 JSONPath 引用

        Args:
            params: 原始参数
            step_results: 已执行的步骤结果
            response_schemas: 步骤对应命令的响应schema字典，key为step_number, value为response_schema

        Returns:
            解析后的参数
        """
        resolved = params.copy()

        # 递归解析所有字符串值
        def resolve_value(value: Any) -> Any:
            if isinstance(value, str):
                # 检测 JSONPath 引用：多种格式支持
                # $.steps[N].response.body.* 或 $.steps[N].response.data[0].* 等
                if value.startswith("$.steps["):
                    return self._extract_from_jsonpath(value, step_results, response_schemas)
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
        step_results: List[StepExecution],
        response_schemas: Dict[int, Dict[str, Any]] = None
    ) -> Any:
        """
        从 JSONPath 提取值

        支持格式：
        - $.steps[N].response.body.field (标准)
        - $.steps[N].response.data[0].field (数组包装)
        - $.steps[N].response.data.field (对象包装)
        - $.steps[N].data[0].field (简化格式)

        优先级：
        1. 使用命令的 response_schema（来自命令集定义）
        2. 如果没有schema，使用智能回退逻辑

        Args:
            jsonpath: JSONPath 表达式
            step_results: 步骤执行结果
            response_schemas: 响应schema映射（步骤号 -> schema定义）

        Returns:
            提取的值
        """
        try:
            # 解析步骤索引
            start_idx = jsonpath.index("[") + 1
            end_idx = jsonpath.index("]")
            step_idx = int(jsonpath[start_idx:end_idx])

            # 获取对应步骤的结果
            # 注意：JSONPath 中的步骤号是 0-indexed，需要转换为 step_number (1-indexed)
            if step_idx >= len(step_results):
                logger.error(f"Invalid step index: {step_idx}, total steps: {len(step_results)}")
                return None

            step = step_results[step_idx]
            if not step.response_data:
                logger.error(f"Step {step.step_number} (index {step_idx}) has no response data")
                return None

            # Compatibility shortcut:
            # some plans still reference list-style JSONPath expressions against
            # MCP.membership.get_member_id results, whose actual payload shape is
            # {member_id, matched_member, ...}. When that happens, resolve
            # directly to response.member_id so execution can continue.
            if isinstance(step.response_data, dict) and "member_id" in step.response_data:
                normalized_jsonpath = jsonpath.replace("full_name", "fullName")
                member_resolution_patterns = (
                    f"$.steps[{step_idx}].response.member_id",
                    f"$.steps[{step_idx}].response.matched_member.id",
                    f"$.steps[{step_idx}].response.id",  # LLM sometimes generates .id instead of .member_id
                )
                if normalized_jsonpath in member_resolution_patterns:
                    return step.response_data.get("member_id")
                if (
                    normalized_jsonpath.startswith(f"$.steps[{step_idx}].response.data[?(")
                    and normalized_jsonpath.endswith(")].id")
                ) or (
                    normalized_jsonpath.startswith(f"$.steps[{step_idx}].response.data[?(")
                    and normalized_jsonpath.endswith("].id")
                ) or (
                    normalized_jsonpath.startswith(f"$.steps[{step_idx}].response.data")
                    and normalized_jsonpath.endswith(".id")
                ):
                    return step.response_data.get("member_id")

            # Compatibility shortcut for role_id resolution:
            # MCP.membership.lookup_role returns {role_id, matched_role, ...} not a list.
            # Some plans still use list-style JSONPath like $.steps[0].response.data[?(@.name == 'X')].id
            if isinstance(step.response_data, dict) and "role_id" in step.response_data:
                normalized_jsonpath = jsonpath
                role_resolution_patterns = (
                    f"$.steps[{step_idx}].response.role_id",
                    f"$.steps[{step_idx}].response.matched_role.id",
                    f"$.steps[{step_idx}].response.id",
                )
                if normalized_jsonpath in role_resolution_patterns:
                    return step.response_data.get("role_id")
                # Handle list-style JSONPath against lookup_role results
                if (
                    normalized_jsonpath.startswith(f"$.steps[{step_idx}].response.data[?(")
                    and normalized_jsonpath.endswith(")].id")
                ) or (
                    normalized_jsonpath.startswith(f"$.steps[{step_idx}].response.data[?(")
                    and normalized_jsonpath.endswith("].id")
                ) or (
                    normalized_jsonpath.startswith(f"$.steps[{step_idx}].response.data")
                    and normalized_jsonpath.endswith(".id")
                ):
                    return step.response_data.get("role_id")

            # 解析路径
            path_str = jsonpath[end_idx + 1:].strip(".")
            if not path_str:
                # 如果没有路径，返回整个响应数据
                return step.response_data

            # 记录原始响应结构用于调试
            logger.debug(f"Extracting from JSONPath: {jsonpath}")
            logger.debug(f"Step {step.step_number} response structure: {json.dumps(step.response_data, indent=2, default=str) if isinstance(step.response_data, (dict, list)) else step.response_data}")

            # 解析路径，支持 data[0].id 这样的格式
            # 首先需要处理带 [] 的部分
            path_parts = self._parse_jsonpath_parts(path_str)

            # 尝试导航到目标字段
            current = step.response_data
            skipped_response = False

            for i, part in enumerate(path_parts):
                if current is None:
                    logger.error(f"Cannot access path at {'.'.join(path_parts[:i])}, value is None")
                    return None

                # 处理过滤器表达式 [?(...)]
                if part.startswith("[?") and part.endswith("]"):
                    # 提取过滤条件，例如 [?(@.name == 'IBC-AI')] -> @.name == 'IBC-AI'
                    filter_expr = part[3:-2]  # 移除 [?( 和 )]
                    
                    if isinstance(current, list):
                        # 尝试应用过滤器
                        filtered = self._apply_jsonpath_filter(current, filter_expr)
                        if filtered is None or (isinstance(filtered, list) and len(filtered) == 0):
                            logger.error(f"JSONPath filter matched no items: {part}")
                            return None
                        current = filtered
                    else:
                        logger.error(f"Cannot apply filter to non-list type: {type(current).__name__}")
                        return None
                    continue

                # 处理数组索引 [N] 格式
                if part.startswith("[") and part.endswith("]"):
                    index_str = part[1:-1]
                    if isinstance(current, list):
                        try:
                            current = current[int(index_str)]
                        except (IndexError, ValueError):
                            logger.error(f"Array index out of bounds: {part}, array length: {len(current) if isinstance(current, list) else 'N/A'}")
                            return None
                    else:
                        logger.error(f"Cannot index non-list with {part}, current type: {type(current).__name__}")
                        return None
                    continue

                # 处理对象字段访问
                if isinstance(current, dict):
                    # 如果是 "response" 并且在响应数据的顶层，跳过它
                    # 因为 response_data 本身就是响应的内容
                    if part == "response" and i == 0 and not skipped_response:
                        skipped_response = True
                        continue

                    # 对常见包装层做兼容：部分 MCP 返回的是实体对象而非 {data: ...}
                    # 若路径要求 .data/.body 但当前没有该键，则尝试按后续访问模式自适配。
                    if part not in current and part in {"data", "body"}:
                        next_part = path_parts[i + 1] if i + 1 < len(path_parts) else None
                        if next_part and next_part.startswith("["):
                            # 后续要做 [0] 或过滤器 [?(...)], 统一包装为单元素列表
                            current = [current]
                            continue
                        # 后续是字段访问，跳过这一层包装名
                        continue

                    # 尝试直接访问
                    if part in current:
                        current = current[part]
                    else:
                        logger.error(f"Cannot access field '{part}' in dict. Available keys: {list(current.keys())}")
                        return None
                elif isinstance(current, list):
                    # 如果不是 [N] 格式，无法在列表上访问字段
                    logger.error(f"Cannot access field '{part}' in list. Expected array index like [0]")
                    return None
                else:
                    logger.error(f"Cannot access path: {part}, current value type: {type(current).__name__}")
                    return None

            return current

        except Exception as e:
            logger.error(f"Failed to parse JSONPath {jsonpath}: {e}")
            
            # 智能回退逻辑：尝试多种可能的响应结构
            try:
                start_idx = jsonpath.index("[") + 1
                end_idx = jsonpath.index("]")
                step_idx = int(jsonpath[start_idx:end_idx])
                
                if step_idx >= len(step_results):
                    logger.error(f"Step index {step_idx} out of range (total: {len(step_results)})")
                    return None
                
                step = step_results[step_idx]
                if not step.response_data:
                    logger.error(f"Step {step.step_number} has no response data")
                    return None
                
                # 提取剩余路径和字段名
                remaining = jsonpath[end_idx + 1:].strip(".")
                
                # 解析需要的字段名（最后一个点后面的内容）
                field_name = remaining.split(".")[-1] if "." in remaining else remaining
                if not field_name or field_name in ["response", "body", "data"]:
                    field_name = None
                
                logger.debug(f"Fallback extraction for step {step_idx}: field_name={field_name}, remaining={remaining}")
                logger.debug(f"Response data type: {type(step.response_data).__name__}")
                if isinstance(step.response_data, dict):
                    logger.debug(f"Response data keys: {list(step.response_data.keys())}")
                elif isinstance(step.response_data, list):
                    logger.debug(f"Response is list with {len(step.response_data)} items")
                    if step.response_data and isinstance(step.response_data[0], dict):
                        logger.debug(f"First item keys: {list(step.response_data[0].keys())}")
                
                # 尝试的路径优先级
                candidates = []
                
                if isinstance(step.response_data, dict):
                    # 1. response.body.data[0] 的形式
                    if "body" in step.response_data and isinstance(step.response_data.get("body"), dict):
                        body = step.response_data["body"]
                        if "data" in body and isinstance(body.get("data"), list) and body["data"]:
                            candidates.append(body["data"][0])
                    
                    # 2. response.data[0] 的形式
                    if "data" in step.response_data:
                        data = step.response_data["data"]
                        if isinstance(data, list) and data:
                            candidates.append(data[0])
                        elif isinstance(data, dict):
                            candidates.append(data)
                    
                    # 3. 尝试其他常见的列表字段名
                    for key in ["members", "roles", "users", "items", "results"]:
                        if key in step.response_data:
                            val = step.response_data[key]
                            if isinstance(val, list) and val:
                                candidates.append(val[0])
                    
                    # 4. response 本身当作第一项
                    candidates.append(step.response_data)
                
                elif isinstance(step.response_data, list) and step.response_data:
                    # 如果响应本身就是列表
                    candidates.append(step.response_data[0])
                
                # 从候选项中查找字段
                if field_name:
                    possible_field_names = [
                        field_name,  # 原始字段名
                        f"_{field_name}",  # _id 的形式
                        f"{field_name}_id",  # member_id 的形式
                    ]
                    
                    for candidate in candidates:
                        if isinstance(candidate, dict):
                            for possible_name in possible_field_names:
                                if possible_name in candidate:
                                    result = candidate[possible_name]
                                    logger.info(f"Fallback: Successfully extracted '{possible_name}' = {result}")
                                    return result
                
                # 如果没找到特定字段，尝试直接返回第一个项
                if candidates and isinstance(candidates[0], dict) and not field_name:
                    logger.info(f"Fallback: Returning first item from candidates")
                    return candidates[0]
                
                logger.error(f"Could not find field '{field_name}' in any candidate structure")
                # 最后的尝试：打印响应数据供调试
                logger.error(f"Response data: {json.dumps(step.response_data, indent=2, default=str)[:500]}")
                return None
                
            except Exception as fallback_e:
                logger.error(f"Fallback JSONPath extraction failed: {fallback_e}", exc_info=True)
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
            original_goal=execution.original_goal,
            steps=[step.model_dump(by_alias=True) for step in steps],
            user_summary=self._build_execution_user_summary(execution, steps),
            repair_hint=self._build_repair_hint(execution, steps),
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

        from src.core.config import settings
        http_client = HTTPClient(base_url=settings.membership_service_url, membership_url=settings.membership_service_url)
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

    def _parse_command_to_mcp(self, command: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse a command string to extract MCP name and tool name.

        This method handles both traditional HTTP commands and MCP commands.
        For example:
        - "POST /v1/members" -> ("membership", "create_member")
        - "GET /v1/members/{id}" -> ("membership", "get_member")
        - "GET /v2/time" -> ("test", "get_time")
        - "MCP.membership.create_member" -> ("membership", "create_member")
        - "MCP.test.get_time" -> ("test", "get_time")

        Args:
            command: The command string to parse

        Returns:
            Tuple of (mcp_name, tool_name) or (None, None) if no match found
        """
        if not command:
            return None, None

        # First, check if it's already an MCP command
        if command.startswith("MCP."):
            # Parse MCP format: "MCP.membership.create_member"
            parts = command.split(".")
            if len(parts) == 3:
                # Skip the "MCP" prefix
                mcp_name = parts[1]
                tool_name = parts[2]
                logger.info(f"Found MCP command: {mcp_name}.{tool_name}")
                return mcp_name, tool_name

        # Define command-to-MCP mappings
        command_mappings = {
            # Membership operations
            "POST /v1/members": ("membership", "create_member"),
            "POST /v1/members/{id}": ("membership", "update_member"),
            "GET /v1/members": ("membership", "list_members"),
            "GET /v1/members/{id}": ("membership", "get_member"),
            "DELETE /v1/members/{id}": ("membership", "delete_member"),
            "GET /v1/roles": ("membership", "list_roles"),
            "POST /v1/members/{id}/roles": ("membership", "assign_role"),

            # Test operations
            "GET /v2/time": ("test", "get_time"),
            "GET /v2/echo": ("test", "echo"),
            "POST /v2/calculate": ("test", "add"),

            # More commands can be added here
        }

        # Exact match first
        if command in command_mappings:
            return command_mappings[command]

        # Pattern matching for dynamic parameters
        for pattern, (mcp_name, tool_name) in command_mappings.items():
            if pattern.endswith("{id}"):
                # Extract the base path
                base_pattern = pattern.replace("/{id}", "")
                base_command = command.rsplit("/", 1)[0]
                if base_command == base_pattern:
                    return mcp_name, tool_name

        # For now, fall back to simple extraction based on path segments
        try:
            parts = command.split()
            if len(parts) >= 2:
                method, path = parts[0], parts[1]

                # Extract the main path segment after /v1/ or /v2/
                if "/v1/" in path or "/v2/" in path:
                    path_segments = path.split("/")
                    if len(path_segments) >= 3:
                        main_segment = path_segments[2]

                        # Map main segments to tools
                        if main_segment == "members":
                            if method == "POST":
                                return "membership", "create_member"
                            elif method == "GET" and len(path_segments) == 3:
                                return "membership", "list_members"
                            elif method == "GET" and len(path_segments) == 4:
                                return "membership", "get_member"
                            elif method == "DELETE" and len(path_segments) == 4:
                                return "membership", "delete_member"
                            elif method == "POST" and len(path_segments) == 4:
                                return "membership", "update_member"
                        elif main_segment == "roles":
                            if method == "GET":
                                return "membership", "list_roles"
                            elif method == "POST" and len(path_segments) > 3:
                                return "membership", "assign_role"
                        elif main_segment == "time":
                            if method == "GET":
                                return "test", "get_time"
                        elif main_segment == "echo":
                            if method == "GET":
                                return "test", "echo"
                        elif main_segment == "calculate":
                            if method == "POST":
                                return "test", "add"

        except Exception as e:
            logger.warning(f"Error parsing command '{command}': {e}")

        return None, None

    def _normalize_mcp_params(
        self,
        mcp_name: str,
        tool_name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = dict(params)

        alias_map = {
            ("membership", "get_member"): {"id": "member_id"},
            ("membership", "update_member"): {"id": "member_id"},
            ("membership", "delete_member"): {"id": "member_id"},
            ("membership", "get_member_orgs"): {"id": "member_id"},
            ("membership", "assign_role"): {"id": "member_id"},
        }

        for source_key, target_key in alias_map.get((mcp_name, tool_name), {}).items():
            if source_key in normalized and target_key not in normalized:
                normalized[target_key] = normalized[source_key]

        return normalized

    def _validate_required_mcp_params(
        self,
        mcp_name: str,
        tool_name: str,
        params: Dict[str, Any],
    ) -> Optional[str]:
        if not self.mcp_registry:
            return None

        tool_info = self.mcp_registry.get_tool_info(mcp_name, tool_name) or {}
        input_schema = tool_info.get("input_schema") or tool_info.get("inputSchema") or {}
        required = [
            name for name in input_schema.get("required", [])
            if name not in {"auth_token", "tenant_id"}
        ]

        missing = []
        for name in required:
            value = params.get(name)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(name)

        if not missing:
            return None

        return (
            f"Plan is missing required parameters for {mcp_name}.{tool_name}: {', '.join(missing)}. "
            "This usually means the plan omitted an intermediate lookup/resolution step."
        )

    def _flatten_mcp_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Flatten parameters for MCP tool execution.
        
        The planning engine structures parameters like:
        {
            "body": {"username": "alice", "email": "alice@example.com"},
            "headers": {"X-Tenant-ID": 1},
            "query": {"page": 1},
            "path": {"id": "123"}
        }
        
        MCP tools expect flat parameters like:
        {
            "username": "alice",
            "email": "alice@example.com"
        }
        
        This method extracts parameters from body, query, and path,
        and ignores headers (those are handled separately).
        
        Args:
            params: The parameters dictionary from the plan
            
        Returns:
            Flattened parameters dictionary suitable for MCP tools
        """
        flattened = {}
        structured_keys = {"body", "query", "path", "headers"}
        has_structured_params = any(
            key in params and isinstance(params.get(key), dict)
            for key in structured_keys
        )

        if not has_structured_params:
            return params.copy()

        if isinstance(params.get("body"), dict):
            flattened.update(params["body"])

        if isinstance(params.get("query"), dict):
            flattened.update(params["query"])

        if isinstance(params.get("path"), dict):
            flattened.update(params["path"])

        for key, value in params.items():
            if key not in structured_keys:
                flattened[key] = value

        return flattened
