import httpx
import logging
from typing import Dict, Any, Optional
from urllib.parse import urljoin
import asyncio
import json
import base64
import time

logger = logging.getLogger(__name__)


class HTTPClient:
    """HTTP 客户端，用于执行 API 请求"""

    def __init__(self, base_url: Optional[str] = None, membership_url: Optional[str] = None):
        """
        初始化 HTTP 客户端

        Args:
            base_url: API 基础 URL（可选，从命令中解析）
            membership_url: Membership service URL for token refresh
        """
        self.base_url = base_url
        self.membership_url = membership_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def execute(
        self,
        command: str,
        params: Dict[str, Any],
        auth_token: Optional[str] = None,
        tenant_id: Optional[int] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        执行 HTTP 请求，支持自动 token 刷新

        Args:
            command: API 命令，如 "POST /users"
            params: 请求参数
            auth_token: JWT token (optional, but required for authenticated endpoints)
            tenant_id: 租户 ID (optional, but required for multi-tenant endpoints)
            timeout: 超时时间（秒）

        Returns:
            API 响应数据

        Raises:
            ValueError: 命令格式无效或缺少必要参数
            httpx.HTTPStatusError: HTTP 错误
        """
        # 解析命令
        method, path = self._parse_command(command)

        # 构建请求参数并处理路径参数
        path, request_params = self._build_request_params(params, path)

        # 构建完整 URL
        url = self._get_full_url(path)

        # 记录请求
        logger.info(f"Executing {method} {url}")

        current_token = auth_token

        # 检查 token 是否即将过期，提前刷新
        if current_token and self._is_token_expired(current_token):
            logger.warning("Token is expired or expiring soon, attempting proactive refresh")
            new_token = await self._refresh_token(current_token)
            if new_token:
                logger.info("Token refreshed proactively")
                current_token = new_token
            else:
                logger.error("Proactive token refresh failed - token may be too expired to refresh")
                # If token is expired and can't be refreshed, we need to require re-login
                raise ValueError("Token expired and cannot be refreshed. Please login again.")

        try:
            # 发送请求 (Python 3.9 compatible)
            response = await self._send_request(
                method=method,
                url=url,
                headers=self._build_headers(current_token, tenant_id),
                request_params=request_params,
                timeout=timeout
            )

            # 处理 401 Unauthorized - 尝试刷新 token
            if response.status_code == 401:
                logger.warning(f"Received 401 Unauthorized, attempting to refresh token")
                logger.debug(f"Response body: {response.text}")
                new_token = await self._refresh_token(current_token)

                if new_token:
                    logger.info("Token refreshed successfully, retrying request")
                    # 用新 token 重试请求
                    response = await self._send_request(
                        method=method,
                        url=url,
                        headers=self._build_headers(new_token, tenant_id),
                        request_params=request_params,
                        timeout=timeout
                    )
                else:
                    logger.error("Failed to refresh token, will proceed with error handling")

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

    async def _send_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        request_params: Dict[str, Any],
        timeout: int
    ) -> httpx.Response:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法
            url: 完整 URL
            headers: 请求头
            request_params: 请求参数
            timeout: 超时时间

        Returns:
            HTTP 响应
        """
        response = await asyncio.wait_for(
            self.client.request(
                method=method,
                url=url,
                headers=headers,
                **request_params
            ),
            timeout=timeout
        )
        return response

    async def _refresh_token(self, current_token: str) -> Optional[str]:
        """
        刷新 JWT token

        Args:
            current_token: 当前 token

        Returns:
            新的 token，如果刷新失败返回 None
        """
        if not self.membership_url:
            logger.warning("Membership URL not configured, cannot refresh token")
            return None

        # Don't attempt refresh if token is None or invalid
        if not current_token or current_token == "None" or not isinstance(current_token, str):
            logger.warning(f"Cannot refresh token: invalid token value '{current_token}'")
            return None

        try:
            refresh_url = urljoin(self.membership_url, "/v2/auth/token/refresh")
            logger.info(f"Refreshing token from {refresh_url}")
            logger.debug(f"Current token (first 20 chars): {current_token[:20] if current_token else 'None'}...")

            response = await asyncio.wait_for(
                self.client.post(
                    refresh_url,
                    headers={
                        "Authorization": f"Bearer {current_token}",
                        "Content-Type": "application/json"
                    }
                ),
                timeout=10
            )

            logger.debug(f"Token refresh response status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                new_token = data.get("access_token")
                if new_token:
                    logger.info("Token refresh successful")
                    return new_token
                else:
                    logger.error("Token refresh response missing access_token")
                    logger.debug(f"Response data: {data}")
                    return None
            else:
                logger.error(f"Token refresh failed with status {response.status_code}: {response.text}")
                return None

        except asyncio.TimeoutError:
            logger.error("Token refresh request timeout")
            return None
        except Exception as e:
            logger.error(f"Error refreshing token: {e}")
            return None

    def _is_token_expired(self, token: str) -> bool:
        """
        检查 JWT token 是否已过期

        Args:
            token: JWT token 字符串

        Returns:
            如果 token 已过期返回 True，否则返回 False
        """
        try:
            # JWT 格式: header.payload.signature
            parts = token.split('.')
            if len(parts) != 3:
                logger.warning("Invalid JWT format")
                return True

            # 解码 payload（第二部分）
            payload = parts[1]
            # 添加填充（如果需要）
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding

            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)

            # 检查 exp 声明
            if 'exp' not in data:
                logger.warning("Token missing exp claim")
                return False

            exp_time = data['exp']
            current_time = time.time()
            time_until_expiry = exp_time - current_time

            # 如果 token 将在 60 秒内过期，认为已过期
            is_expired = time_until_expiry < 60

            if is_expired:
                logger.warning(f"Token expires in {time_until_expiry:.0f} seconds, treating as expired")
            else:
                logger.debug(f"Token valid for {time_until_expiry:.0f} more seconds")

            return is_expired

        except Exception as e:
            logger.warning(f"Error checking token expiration: {e}")
            return False

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

    def _build_headers(self, auth_token: Optional[str], tenant_id: Optional[int]) -> Dict[str, str]:
        """
        构建请求头

        Args:
            auth_token: JWT token (optional)
            tenant_id: 租户 ID (optional)

        Returns:
            请求头字典
        """
        headers = {
            "Content-Type": "application/json"
        }

        # Only add auth header if token is provided
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        # Only add tenant header if tenant_id is provided
        if tenant_id is not None:
            headers["X-Tenant-ID"] = str(tenant_id)

        return headers

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
                if value is None:
                    raise ValueError(f"Path parameter '{key}' is None. This usually means a previous step failed to extract the required value. Cannot proceed without this value.")
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