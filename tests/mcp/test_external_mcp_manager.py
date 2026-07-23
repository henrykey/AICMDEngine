import asyncio
from pathlib import Path

import pytest

from src.mcp.external_mcp_manager import (
    ExternalMCPManager,
    load_external_mcp_config,
)
from src.mcp.registry import MCPRegistry


class FakeExternalMCP:
    def __init__(self, name, should_fail=False, **config):
        self.name = name
        self.version = "1.0"
        self.external_config = config
        self.should_fail = should_fail
        self.initialized = False
        self.closed = False

    async def initialize(self):
        if self.should_fail:
            raise RuntimeError("connection failed")
        self.initialized = True

    async def close(self):
        self.closed = True

    def get_info(self):
        return {"tools": [{"name": "example_tool"}]}


def test_load_external_mcp_config_supports_servers_wrapper(tmp_path):
    config_path = tmp_path / "external_mcps.yml"
    config_path.write_text(
        "servers:\n"
        "  example:\n"
        "    transport: http\n"
        "    url: http://example:9000\n"
    )

    result = load_external_mcp_config(config_path)

    assert result == {
        "example": {
            "transport": "http",
            "url": "http://example:9000",
        }
    }


def test_load_external_mcp_config_rejects_invalid_root(tmp_path):
    config_path = tmp_path / "external_mcps.yml"
    config_path.write_text("- invalid\n- config\n")

    with pytest.raises(ValueError, match="mapping"):
        load_external_mcp_config(config_path)


def test_refresh_adds_updates_and_removes_servers():
  asyncio.run(_refresh_adds_updates_and_removes_servers())


async def _refresh_adds_updates_and_removes_servers():
    registry = MCPRegistry()
    configs = {
        "alpha": {"transport": "http", "url": "http://alpha:9000"},
        "remove-me": {"transport": "http", "url": "http://remove:9000"},
    }
    created = []

    def factory(name, config):
        server = FakeExternalMCP(name=name, **config)
        created.append(server)
        return server

    manager = ExternalMCPManager(
        registry=registry,
        config_loader=lambda: configs,
        server_factory=factory,
    )

    first = await manager.refresh()
    old_alpha = registry.get_mcp("alpha")
    removed_server = registry.get_mcp("remove-me")

    assert first["added"] == ["alpha", "remove-me"]
    assert first["failed"] == {}

    configs = {
        "alpha": {"transport": "http", "url": "http://alpha:9001"},
        "beta": {"transport": "http", "url": "http://beta:9000"},
    }
    second = await manager.refresh()

    assert second["added"] == ["beta"]
    assert second["updated"] == ["alpha"]
    assert second["removed"] == ["remove-me"]
    assert "mcp:0:alpha:example_tool" in second["stale_external_ids"]
    assert "mcp:0:remove-me:example_tool" in second["stale_external_ids"]
    assert registry.get_mcp("alpha") is not old_alpha
    assert old_alpha.closed is True
    assert removed_server.closed is True
    assert registry.get_mcp("remove-me") is None


def test_failed_update_keeps_existing_server():
  asyncio.run(_failed_update_keeps_existing_server())


async def _failed_update_keeps_existing_server():
    registry = MCPRegistry()
    configs = {"alpha": {"transport": "http", "url": "http://alpha:9000"}}

    def factory(name, config):
        return FakeExternalMCP(
            name=name,
            should_fail=config.get("url", "").endswith("bad"),
            **config,
        )

    manager = ExternalMCPManager(
        registry=registry,
        config_loader=lambda: configs,
        server_factory=factory,
    )
    await manager.refresh()
    original = registry.get_mcp("alpha")

    configs = {"alpha": {"transport": "http", "url": "http://alpha:bad"}}
    result = await manager.refresh()

    assert "alpha" in result["failed"]
    assert result["updated"] == []
    assert registry.get_mcp("alpha") is original
    assert original.closed is False


def test_invalid_config_does_not_change_registry():
  asyncio.run(_invalid_config_does_not_change_registry())


async def _invalid_config_does_not_change_registry():
    registry = MCPRegistry()
    manager = ExternalMCPManager(
        registry=registry,
        config_loader=lambda: {"alpha": {"url": "http://alpha"}},
        server_factory=lambda name, config: FakeExternalMCP(name=name, **config),
    )
    await manager.refresh()
    original = registry.get_mcp("alpha")

    manager.config_loader = lambda: (_ for _ in ()).throw(ValueError("bad yaml"))
    result = await manager.refresh()

    assert result["success"] is False
    assert result["error"] == "bad yaml"
    assert registry.get_mcp("alpha") is original
