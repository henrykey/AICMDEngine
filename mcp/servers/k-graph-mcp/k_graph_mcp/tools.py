"""Authorized MCP tool boundary for the BasinComparator graph server."""

from __future__ import annotations

from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from .contracts import (
  AuthorizedScopeEnvelope,
  canonical_scope_fingerprint,
)


class GraphBackend(Protocol):
  def start(
    self,
    scope: AuthorizedScopeEnvelope,
    service_token: str | None = None,
    vlm_config: dict[str, Any] | None = None,
    force_rebuild: bool = False,
  ) -> dict[str, Any]: ...

  def status(
    self,
    build_id: str,
    scope: AuthorizedScopeEnvelope,
    service_token: str | None = None,
    vlm_config: dict[str, Any] | None = None,
  ) -> dict[str, Any]: ...

  def query(
    self,
    scope: AuthorizedScopeEnvelope,
    *,
    graph_version_id: str | None,
    basin: str | None,
    target: str | None,
  ) -> dict[str, Any]: ...


class UnavailableGraphBackend:
  def start(
    self,
    scope: AuthorizedScopeEnvelope,
    service_token: str | None = None,
    vlm_config: dict[str, Any] | None = None,
    force_rebuild: bool = False,
  ) -> dict[str, Any]:
    raise RuntimeError("G29.2 asynchronous build backend is not implemented")

  def status(
    self,
    build_id: str,
    scope: AuthorizedScopeEnvelope,
    service_token: str | None = None,
    vlm_config: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    raise RuntimeError("G29.2 asynchronous build backend is not implemented")

  def query(
    self,
    scope: AuthorizedScopeEnvelope,
    *,
    graph_version_id: str | None,
    basin: str | None,
    target: str | None,
  ) -> dict[str, Any]:
    raise RuntimeError("G29.2 graph query backend is not implemented")


class BasinGraphTools:
  def __init__(self, *, backend: GraphBackend):
    self._backend = backend

  def start_basin_graph_build(
    self,
    scope: AuthorizedScopeEnvelope,
    service_token: str,
    vlm_config: dict[str, Any] | None = None,
    force_rebuild: bool = False,
  ) -> dict[str, Any]:
    if not service_token or not service_token.strip():
      raise ValueError("service_token is required")
    self._validate_scope(scope)
    return self._backend.start(scope, service_token, vlm_config, force_rebuild)

  def get_basin_graph_build_status(
    self,
    build_id: str,
    scope: AuthorizedScopeEnvelope,
    service_token: str,
    vlm_config: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    if not build_id or not build_id.strip():
      raise ValueError("build_id is required")
    if not service_token or not service_token.strip():
      raise ValueError("service_token is required")
    self._validate_scope(scope)
    return self._backend.status(build_id, scope, service_token, vlm_config)

  def query_basin_graph(
    self,
    scope: AuthorizedScopeEnvelope,
    graph_version_id: str | None = None,
    basin: str | None = None,
    target: str | None = None,
  ) -> dict[str, Any]:
    if not basin and not target:
      raise ValueError("basin or target is required")
    self._validate_scope(scope)
    return self._backend.query(
      scope,
      graph_version_id=graph_version_id,
      basin=basin,
      target=target,
    )

  def _validate_scope(self, scope: AuthorizedScopeEnvelope) -> None:
    if scope.scope_fingerprint is None:
      raise ValueError("scope_fingerprint is required")
    if scope.scope_fingerprint != canonical_scope_fingerprint(scope):
      raise ValueError(
        "scope_fingerprint does not match the selected documents"
      )


def create_mcp(
  *,
  backend: GraphBackend | None = None,
  host: str = "127.0.0.1",
  port: int = 8000,
) -> FastMCP:
  tools = BasinGraphTools(backend=backend or UnavailableGraphBackend())
  mcp = FastMCP(
    "k-graph-mcp",
    host=host,
    port=port,
    instructions=(
      "Build and query only Membership-authorized BasinComparator entity graphs."
    ),
  )
  mcp.tool(
    description=(
      "Start an asynchronous basin graph build for an exact Membership-authorized "
      "document group."
    )
  )(tools.start_basin_graph_build)
  mcp.tool(
    description=(
      "Get build status after reauthorizing the same tenant, project, and document "
      "scope through Membership."
    )
  )(tools.get_basin_graph_build_status)
  mcp.tool(
    description=(
      "Query a completed authorized graph by basin or target with source evidence."
    )
  )(tools.query_basin_graph)
  return mcp
