import httpx
import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin
import asyncio

logger = logging.getLogger(__name__)


class HTTPClient:
    """HTTP 客户端，用于执行 API 请求"""

    def __init__(self, base_url: Optional[str] = None):
        """
        初始化 HTTP 客户端

        Args:
            base_url: API 基础 URL（可选，从命令中解析）
        """
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def execute(
        self,
        command: str,
        params: Dict[str, Any],
        auth_token: str,
        tenant_id: int,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        执行 HTTP 请求

        Args:
            command: API 命令，如 "POST /users"
            params: 请求参数
            auth_token: JWT token
            tenant_id: 租户 ID
            timeout: 超时时间（秒）

        Returns:
            API 响应数据

        Raises:
            ValueError: 命令格式无效
            httpx.HTTPStatusError: HTTP 错误
        """
        # 解析命令
        method, path = self._parse_command(command)

        # 构建请求头
        headers = self._build_headers(auth_token, tenant_id)

        # 构建请求参数并处理路径参数
        path, request_params = self._build_request_params(params, path)

        # 构建完整 URL
        url = self._get_full_url(path)

        # 记录请求
        logger.info(f"Executing {method} {url}")

        try:
            # 发送请求 (Python 3.9 compatible)
            response = await asyncio.wait_for(
                self.client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    **request_params
                ),
                timeout=timeout
            )

            # 处理错误响应
            if response.status_code >= 400:
                error_detail = self._extract_error_detail(response)
                logger.error(f"HTTP {response.status_code}: {error_detail}")
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}: {error_detail}",
                    request=response.request,
                    response=response
                )

            # 解析响应 - 处理 204 No Content 响应
            if response.status_code == 204:
                logger.info(f"Request successful (no content): {method} {url}")
                return {}

            response_data = response.json()
            logger.info(f"Request successful: {method} {url}")

            return response_data

        except asyncio.TimeoutError:
            logger.error(f"Request timeout after {timeout}s: {method} {url}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            raise

    def _parse_command(self, command: str) -> tuple:
        """
        解析命令字符串

        Args:
            command: 命令字符串，如 "POST /users"

        Returns:
            (method, path) 元组

        Raises:
            ValueError: 命令格式无效
        """
        parts = command.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid command format: {command}")

        method = parts[0].upper()
        path = parts[1]

        if method not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            raise ValueError(f"Unsupported HTTP method: {method}")

        return method, path

    def _get_full_url(self, path: str) -> str:
        """
        构建完整的 URL

        Args:
            path: 路径，如 "/users"

        Returns:
            完整 URL
        """
        if self.base_url:
            return urljoin(self.base_url, path)
        return path

    def _build_headers(self, auth_token: str, tenant_id: int) -> Dict[str, str]:
        """
        构建请求头

        Args:
            auth_token: JWT token
            tenant_id: 租户 ID

        Returns:
            请求头字典
        """
        return {
            "Authorization": f"Bearer {auth_token}",
            "X-Tenant-ID": str(tenant_id),
            "Content-Type": "application/json"
        }

    def _build_request_params(self, params: Dict[str, Any], path: str) -> tuple:
        """
        构建请求参数

        Args:
            params: 参数字典
            path: URL 路径（用于替换路径参数）

        Returns:
            (updated_path, httpx 请求参数) 元组

        Note: Headers are handled separately by the caller via _build_headers()
              so we don't include them in the returned params to avoid conflicts.
        """
        request_params = {}

        # Path parameters - 替换路径中的 {key} 占位符
        if "path" in params:
            for key, value in params["path"].items():
                path = path.replace(f"{{{key}}}", str(value))

        # Query parameters
        if "query" in params:
            request_params["params"] = params["query"]

        # Request body
        if "body" in params:
            request_params["json"] = params["body"]

        return path, request_params

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

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()