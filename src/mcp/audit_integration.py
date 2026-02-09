"""
Simple Audit Integration for AICMDEngine

Record audit logs by calling membership MCP service.
Extract all info from JWT token.
"""

from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class SimpleAuditLogger:
    """简单的审计日志记录器"""

    def __init__(self, mcp_registry):
        """
        初始化

        Args:
            mcp_registry: MCP 注册表
        """
        self.mcp_registry = mcp_registry
        self.membership_name = "membership"

    async def log_operation(
        self,
        tenant_id: int,
        member_id: int,
        action: str,
        category: str = "API",
        tool_name: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        记录操作审计日志

        Args:
            tenant_id: 租户ID（从 JWT 提取）
            member_id: 会员ID（从 JWT 提取）
            action: 操作名称（如：MCP_TOOL_CALL, CREATE_DOCUMENT）
            category: 分类（API, SYSTEM, AUTH, DATA）
            tool_name: 工具名称（可选）
            arguments: 工具参数（可选，会脱敏）
            success: 是否成功
            error_message: 错误信息（失败时）
            metadata: 额外元数据
        """
        # 构建 actor
        actor = {
            "memberId": member_id
        }

        # 构建 target（如果有工具名）
        target = None
        if tool_name:
            target = {
                "type": "mcp_tool",
                "id": tool_name
            }

        # 构建 metadata
        audit_metadata = {
            "service": "aicmdengine"
        }

        if arguments:
            audit_metadata["parameters"] = self._sanitize_arguments(arguments)

        if error_message:
            audit_metadata["error_message"] = error_message

        if metadata:
            audit_metadata.update(metadata)

        # 构建事件
        audit_event = {
            "category": category,
            "action": action,
            "tenant_id": tenant_id,
            "actor": actor
        }

        if target:
            audit_event["target"] = target

        if audit_metadata:
            audit_event["metadata"] = audit_metadata

        # 提交审计事件
        try:
            await self.mcp_registry.execute_command(
                mcp_name=self.membership_name,
                tool_name="submit_audit_event",
                **audit_event
            )
            logger.debug(f"Audit log recorded: {action} - {member_id}")
        except Exception as e:
            logger.error(f"Failed to record audit log: {e}")

    def _sanitize_arguments(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        脱敏敏感参数

        Args:
            arguments: 原始参数

        Returns:
            dict: 脱敏后的参数
        """
        import copy

        sanitized = copy.deepcopy(arguments)

        sensitive_keywords = [
            "password", "token", "secret", "key",
            "credential", "authorization"
        ]

        def sanitize_value(key: str, value: Any) -> Any:
            if isinstance(value, dict):
                return {k: sanitize_value(k, v) for k, v in value.items()}
            elif isinstance(value, list):
                return [sanitize_value(key, item) for item in value]
            elif isinstance(value, str):
                if any(kw in key.lower() for kw in sensitive_keywords):
                    return "***REDACTED***"
            return value

        return {k: sanitize_value(k, v) for k, v in sanitized.items()}
