import logging
from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime

from src.models.execution import (
    ExecutionRecord,
    ExecutionStatus,
    StepExecution,
    StepStatus
)

logger = logging.getLogger(__name__)


class ExecutionRepository:
    """执行数据仓储"""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        初始化仓储

        Args:
            db: MongoDB 异步数据库实例
        """
        self.db = db

    async def create_execution(
        self,
        tenant_id: int,
        plan_id: str,
        plan: list,
        global_timeout: int,
        created_by: str
    ) -> ExecutionRecord:
        """
        创建执行记录

        Args:
            tenant_id: 租户 ID
            plan_id: 计划 ID
            plan: 计划步骤列表
            global_timeout: 全局超时时间
            created_by: 创建者用户 ID

        Returns:
            创建的执行记录
        """
        execution = ExecutionRecord(
            tenant_id=tenant_id,
            plan_id=plan_id,
            total_steps=len(plan),
            global_timeout=global_timeout,
            created_by=created_by
        )

        result = await self.db["executions"].insert_one(
            execution.model_dump(by_alias=True, exclude={"id"})
        )

        execution.id = str(result.inserted_id)
        logger.info(f"Created execution record: {execution.id}")

        return execution

    async def get_execution(self, execution_id: str) -> Optional[ExecutionRecord]:
        """
        获取执行记录

        Args:
            execution_id: 执行记录 ID

        Returns:
            执行记录，不存在则返回 None
        """
        doc = await self.db["executions"].find_one({"_id": ObjectId(execution_id)})
        if doc:
            return ExecutionRecord(**doc)
        return None

    async def update_execution(
        self,
        execution_id: str,
        **updates
    ) -> bool:
        """
        更新执行记录

        Args:
            execution_id: 执行记录 ID
            **updates: 要更新的字段

        Returns:
            是否更新成功
        """
        result = await self.db["executions"].update_one(
            {"_id": ObjectId(execution_id)},
            {"$set": updates}
        )
        logger.info(f"Updated execution {execution_id}: {list(updates.keys())}")
        return result.modified_count > 0

    async def create_step(
        self,
        execution_id: str,
        step_number: int,
        command: str,
        description: str,
        timeout: int
    ) -> StepExecution:
        """
        创建步骤执行记录

        Args:
            execution_id: 执行记录 ID
            step_number: 步骤编号
            command: 命令字符串
            description: 步骤描述
            timeout: 超时时间

        Returns:
            创建的步骤执行记录
        """
        step = StepExecution(
            execution_id=execution_id,
            step_number=step_number,
            command=command,
            description=description,
            timeout=timeout,
            status=StepStatus.PENDING
        )

        result = await self.db["step_executions"].insert_one(
            step.model_dump(by_alias=True, exclude={"id"})
        )

        step.id = str(result.inserted_id)
        return step

    async def update_step(
        self,
        step_id: str,
        **updates
    ) -> bool:
        """
        更新步骤执行记录

        Args:
            step_id: 步骤 ID
            **updates: 要更新的字段

        Returns:
            是否更新成功
        """
        result = await self.db["step_executions"].update_one(
            {"_id": ObjectId(step_id)},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def get_steps(
        self,
        execution_id: str,
        status: Optional[StepStatus] = None
    ) -> List[StepExecution]:
        """
        获取执行记录的所有步骤

        Args:
            execution_id: 执行记录 ID
            status: 可选的状态过滤

        Returns:
            步骤执行记录列表
        """
        query = {"execution_id": execution_id}
        if status:
            query["status"] = status

        cursor = self.db["step_executions"].find(query)
        steps = []
        async for doc in cursor:
            steps.append(StepExecution(**doc))
        return steps

    async def write_audit_log(
        self,
        tenant_id: int,
        category: str,
        action: str,
        resource: str,
        subject: str,
        payload: Dict[str, Any]
    ):
        """
        写入审计日志（遵循 Membership 审计事件格式）

        Args:
            tenant_id: 租户 ID
            category: 类别（如 task_execution）
            action: 操作（如 plan_started）
            resource: 资源标识
            subject: 主体（用户 ID）
            payload: 载荷数据
        """
        try:
            await self.db["events"].insert_one({
                "tenant_id": tenant_id,
                "category": category,
                "action": action,
                "resource": resource,
                "subject": subject,
                "payload_masked": self._mask_sensitive_data(payload),
                "occurred_at": datetime.utcnow()
            })
            logger.info(f"Audit log written: {action} on {resource}")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    def _mask_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        脱敏敏感数据

        Args:
            data: 原始数据

        Returns:
            脱敏后的数据
        """
        # 简单脱敏：移除或掩盖特定字段
        masked = data.copy()

        sensitive_keys = ["password", "token", "secret", "key", "api_key"]
        for key in list(masked.keys()):
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                if isinstance(masked[key], str):
                    masked[key] = "***"
                elif isinstance(masked[key], dict):
                    # 递归脱敏字典
                    masked[key] = self._mask_sensitive_data(masked[key])
                elif isinstance(masked[key], list):
                    masked[key] = "[MASKED]"

        return masked