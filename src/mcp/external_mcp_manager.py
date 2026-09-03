"""Runtime configuration and lifecycle management for external MCP servers."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict

import yaml

from .external_mcp import ExternalMCPServer
from .registry import MCPRegistry


logger = logging.getLogger(__name__)


def load_external_mcp_config(path: str | Path) -> Dict[str, Dict[str, Any]]:
    """Load an external MCP mapping from YAML."""
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"External MCP config file does not exist: {config_path}")

    raw = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("External MCP config root must be a mapping")

    servers = raw.get("servers", raw)
    if not isinstance(servers, dict):
        raise ValueError("External MCP 'servers' value must be a mapping")

    normalized: Dict[str, Dict[str, Any]] = {}
    for name, config in servers.items():
        if not isinstance(name, str) or not name:
            raise ValueError("External MCP names must be non-empty strings")
        if not isinstance(config, dict):
            raise ValueError(f"External MCP '{name}' config must be a mapping")
        normalized[name] = dict(config)
    return normalized


def create_external_mcp(name: str, config: Dict[str, Any]) -> ExternalMCPServer:
    """Construct an ExternalMCPServer from normalized configuration."""
    server = ExternalMCPServer(
        name=name,
        command=config.get("command"),
        args=config.get("args", []),
        transport=config.get("transport", "stdio"),
        url=config.get("url"),
        env=config.get("env"),
        timeout=config.get("timeout", 30),
    )
    server.external_config = dict(config)
    return server


class ExternalMCPManager:
    """Apply external MCP configuration changes without restarting the router."""

    def __init__(
        self,
        registry: MCPRegistry,
        config_loader: Callable[[], Dict[str, Dict[str, Any]]],
        server_factory: Callable[[str, Dict[str, Any]], Any] = create_external_mcp,
    ):
        self.registry = registry
        self.config_loader = config_loader
        self.server_factory = server_factory
        self.managed_names: set[str] = set()
        self._lock = asyncio.Lock()

    async def refresh(self) -> Dict[str, Any]:
        """Load desired configuration and atomically replace each changed server."""
        async with self._lock:
            try:
                desired = self.config_loader()
            except Exception as exc:
                logger.error("Failed to load external MCP configuration: %s", exc)
                return {
                    "success": False,
                    "added": [],
                    "updated": [],
                    "removed": [],
                    "unchanged": [],
                    "failed": {},
                    "error": str(exc),
                }

            result: Dict[str, Any] = {
                "success": True,
                "added": [],
                "updated": [],
                "removed": [],
                "unchanged": [],
                "failed": {},
                "stale_external_ids": [],
                "reconnecting": [],
            }

            for name, config in desired.items():
                current = self.registry.get_mcp(name) if name in self.managed_names else None
                if current is not None and getattr(current, "external_config", {}) == config:
                    result["unchanged"].append(name)
                    continue

                replacement = None
                try:
                    replacement = self.server_factory(name, config)
                    replacement.external_config = dict(config)
                    await replacement.initialize()
                except Exception as exc:
                    if replacement is not None and current is None:
                        self.registry.register_mcp(replacement)
                        self.managed_names.add(name)
                        schedule_reconnect = getattr(
                            replacement,
                            "schedule_reconnect",
                            None,
                        )
                        if schedule_reconnect:
                            schedule_reconnect()
                        result["reconnecting"].append(name)
                    elif replacement is not None:
                        await self._close_server(replacement)
                    result["failed"][name] = str(exc)
                    result["success"] = False
                    if name in result["reconnecting"]:
                        logger.debug(
                            "External MCP '%s' is unavailable and reconnecting in the background: %s",
                            name,
                            exc,
                        )
                    else:
                        logger.error("Failed to initialize external MCP '%s': %s", name, exc)
                    continue

                self.registry.register_mcp(replacement)
                self.managed_names.add(name)
                if current is None:
                    result["added"].append(name)
                else:
                    result["stale_external_ids"].extend(
                        self._tool_external_ids(current)
                    )
                    result["updated"].append(name)
                    await self._close_server(current)

            for name in sorted(self.managed_names - set(desired)):
                current = self.registry.get_mcp(name)
                if current is not None:
                    result["stale_external_ids"].extend(
                        self._tool_external_ids(current)
                    )
                    await self._close_server(current)
                    self.registry.remove_mcp(name)
                self.managed_names.discard(name)
                result["removed"].append(name)

            return result

    @staticmethod
    def _tool_external_ids(server: Any) -> list[str]:
        try:
            tools = server.get_info().get("tools", [])
        except Exception:
            return []
        return [
            f"mcp:0:{server.name}:{tool.get('name', '')}"
            for tool in tools
            if isinstance(tool, dict) and tool.get("name")
        ]

    async def close(self) -> None:
        """Close all external MCP servers managed by this instance."""
        async with self._lock:
            for name in sorted(self.managed_names):
                server = self.registry.get_mcp(name)
                if server is not None:
                    await self._close_server(server)
            self.managed_names.clear()

    @staticmethod
    async def _close_server(server: Any) -> None:
        close = getattr(server, "close", None)
        if not close:
            return
        try:
            await close()
        except Exception as exc:
            logger.warning("Failed to close external MCP '%s': %s", server.name, exc)
