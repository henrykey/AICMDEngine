import httpx
import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from src.core.config import settings

logger = logging.getLogger(__name__)


class MembershipClient:
    """Membership Service Client - 用于与 Membership 服务交互"""

    def __init__(self):
        """初始化 Membership 客户端"""
        self.base_url = settings.membership_service_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def create_member(
        self,
        tenant_id: int,
        username: str,
        email: str,
        password: str,
        is_virtual: bool = True,
        auth_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建成员用户

        Args:
            tenant_id: 租户 ID
            username: 用户名
            email: 邮箱
            password: 密码
            is_virtual: 是否为虚拟用户
            auth_token: JWT token（可选，某些情况下可能需要）

        Returns:
            创建响应数据

        Raises:
            httpx.HTTPStatusError: HTTP 错误
        """
        url = urljoin(self.base_url, "/v2/members")

        # 构建请求头
        headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": str(tenant_id)
        }

        # 如果有认证 token，添加到请求头
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        # 构建请求体
        payload = {
            "username": username,
            "email": email,
            "password": password,
            "is_virtual": is_virtual
        }

        logger.info(f"Creating member: {username} for tenant: {tenant_id}")

        try:
            response = await self.client.post(url, json=payload, headers=headers)

            # 处理错误响应
            if response.status_code >= 400:
                error_detail = self._extract_error_detail(response)
                logger.error(f"Failed to create member: HTTP {response.status_code} - {error_detail}")
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}: {error_detail}",
                    request=response.request,
                    response=response
                )

            # 解析响应
            response_data = response.json()
            logger.info(f"Member created successfully: {username}")

            return response_data

        except httpx.HTTPError as e:
            logger.error(f"HTTP error creating member: {e}")
            raise

    async def get_member(self, tenant_id: int, member_id: str, auth_token: Optional[str] = None) -> Dict[str, Any]:
        """
        获取成员信息

        Args:
            tenant_id: 租户 ID
            member_id: 成员 ID
            auth_token: JWT token（可选）

        Returns:
            成员信息
        """
        url = urljoin(self.base_url, f"/v2/members/{member_id}")

        # 构建请求头
        headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": str(tenant_id)
        }

        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"HTTP error getting member: {e}")
            raise

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()

    def _extract_error_detail(self, response: httpx.Response) -> str:
        """
        从错误响应中提取错误信息

        Args:
            response: HTTP 错误响应

        Returns:
            错误信息字符串
        """
        try:
            error_data = response.json()
            if isinstance(error_data, dict):
                return error_data.get("detail", str(error_data))
            return str(error_data)
        except Exception:
            return response.text