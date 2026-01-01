from typing import Optional
from fastapi import Header, HTTPException, status
from src.core.config import settings

async def get_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")
) -> int:
    """
    获取当前请求的租户 ID。

    逻辑优先级:
    1. 如果配置文件中设置了 FIXED_TENANT_ID (私有部署/调试模式)，则强制使用该 ID。
    2. 否则，必须从 HTTP Header `X-Tenant-ID` 中获取。
    3. 如果两者都没有，抛出 400 错误。
    """
    # 1. 优先检查强制配置 (私有化部署/开发便利)
    if settings.fixed_tenant_id is not None:
        return int(settings.fixed_tenant_id)

    # 2. 检查请求头 (SaaS 多租户模式 - 标准路径)
    if x_tenant_id:
        try:
            return int(x_tenant_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid tenant ID format: '{x_tenant_id}'. Must be an integer."
            )

    # 3. 均未找到，拒绝请求
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Missing 'X-Tenant-ID' header. Please specify the tenant context."
    )