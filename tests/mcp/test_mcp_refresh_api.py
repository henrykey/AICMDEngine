import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.core.config import settings
from src.routers.mcp import (
    _require_mcp_admin_token,
    refresh_external_mcp_config,
)


class FakeManager:
    async def refresh(self):
        return {
            "success": True,
            "added": ["new-server"],
            "updated": [],
            "removed": [],
            "unchanged": [],
            "failed": {},
        }


def test_admin_token_is_required_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "mcp_admin_token", "secret")

    with pytest.raises(HTTPException) as exc:
        _require_mcp_admin_token("wrong")

    assert exc.value.status_code == 403
    _require_mcp_admin_token("secret")


def test_missing_production_admin_token_disables_refresh(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "mcp_admin_token", "")

    with pytest.raises(HTTPException) as exc:
        _require_mcp_admin_token(None)

    assert exc.value.status_code == 503


def test_refresh_endpoint_applies_manager_result(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "mcp_admin_token", "")
    request = SimpleNamespace(
        app=SimpleNamespace(
            external_mcp_manager=FakeManager(),
            mcp_registry=object(),
        )
    )

    result = asyncio.run(
        refresh_external_mcp_config(request, x_mcp_admin_token=None)
    )

    assert result["added"] == ["new-server"]
