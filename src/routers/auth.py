"""
Authentication router - delegates to Membership Service or configured auth backend
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import httpx
from src.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    """Login request payload"""
    username: str
    password: str
    device_id: Optional[str] = None


class LoginResponse(BaseModel):
    """Login response payload"""
    username: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: int = 3600
    member_id: Optional[int] = None
    full_name: Optional[str] = None
    device_id: Optional[str] = None
    auto_login_token: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class TokenRefreshRequest(BaseModel):
    """Refresh token request payload"""
    refresh_token: str


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, http_request: Request):
    """
    Authenticate user against configured auth backend.
    Currently delegates to Membership Service.

    In the future, this can be easily changed to use LDAP, OAuth2, or any other auth system.
    """
    tenant_id = http_request.headers.get("X-Tenant-ID", "1")

    try:
        # Call Membership Service
        membership_url = settings.membership_service_url
        login_endpoint = f"{membership_url}/v2/auth/login"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                login_endpoint,
                json={
                    "username": request.username,
                    "password": request.password,
                    "device_id": request.device_id or "nl-tps-default"
                },
                headers={
                    "X-Tenant-ID": str(tenant_id),
                    "Content-Type": "application/json"
                }
            )

        if response.status_code != 200:
            logger.error(f"Membership auth failed: {response.status_code}")
            return LoginResponse(
                error_code="AUTH_FAILED",
                error_message="Authentication failed"
            )

        # Parse response from Membership Service
        data = response.json()

        # Return the response as-is (it already has the right structure)
        return LoginResponse(**data)

    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return LoginResponse(
            error_code="INTERNAL_ERROR",
            error_message=f"Login failed: {str(e)}"
        )


@router.post("/token/refresh", response_model=LoginResponse)
async def refresh_token(request: TokenRefreshRequest, http_request: Request):
    """
    Refresh access token against Membership Service.
    """
    tenant_id = http_request.headers.get("X-Tenant-ID", "1")

    try:
        membership_url = settings.membership_service_url
        refresh_endpoint = f"{membership_url}/v2/auth/token/refresh"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                refresh_endpoint,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": request.refresh_token,
                },
                headers={
                    "X-Tenant-ID": str(tenant_id),
                    "Content-Type": "application/json",
                }
            )

        if response.status_code != 200:
            logger.warning("Membership token refresh failed: %s", response.status_code)
            return LoginResponse(
                error_code="TOKEN_REFRESH_FAILED",
                error_message="Token refresh failed"
            )

        data = response.json()
        return LoginResponse(**data)

    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        return LoginResponse(
            error_code="INTERNAL_ERROR",
            error_message=f"Token refresh failed: {str(e)}"
        )
