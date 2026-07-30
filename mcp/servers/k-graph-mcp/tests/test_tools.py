import asyncio

import pytest

from k_graph_mcp.contracts import (
  AuthorizedScopeEnvelope,
  DocumentScopeItem,
  canonical_scope_fingerprint,
)
from k_graph_mcp.tools import BasinGraphTools, create_mcp


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


class RecordingBackend:
  def __init__(self):
    self.calls: list[tuple[str, object]] = []

  def start(self, scope, service_token=None, vlm_config=None, force_rebuild=False):
    self.calls.append(("start", (scope, vlm_config, force_rebuild)))
    return {"build_id": "build-1", "status": "QUEUED"}

  def status(self, build_id, scope, service_token=None, vlm_config=None):
    self.calls.append(("status", (build_id, scope, vlm_config)))
    return {"build_id": build_id, "status": "RUNNING"}

  def query(self, scope, *, graph_version_id, basin, target):
    self.calls.append((
      "query",
      (scope, graph_version_id, basin, target),
    ))
    return {"graph_version_id": graph_version_id, "entities": []}


def test_start_validates_scope_before_calling_backend() -> None:
  backend = RecordingBackend()
  tools = BasinGraphTools(backend=backend)
  scope = selected_scope()

  result = tools.start_basin_graph_build(scope, "service-token")

  assert result["build_id"] == "build-1"
  assert backend.calls == [("start", (scope, None, False))]


def test_start_forwards_explicit_force_rebuild() -> None:
  backend = RecordingBackend()
  tools = BasinGraphTools(backend=backend)
  selected = selected_scope()

  tools.start_basin_graph_build(
    selected,
    "service-token",
    force_rebuild=True,
  )

  assert backend.calls == [("start", (selected, None, True))]


def test_start_forwards_runtime_provider_without_persisting_it_in_scope() -> None:
  backend = RecordingBackend()
  tools = BasinGraphTools(backend=backend)
  scope = selected_scope()
  runtime_provider = {
    "provider": "Qwen",
    "model": "qwen-plus",
    "base_url": "https://dashscope.example/v1",
    "api_key": "runtime-secret",
  }

  tools.start_basin_graph_build(
    scope,
    "service-token",
    vlm_config=runtime_provider,
  )

  assert backend.calls == [("start", (scope, runtime_provider, False))]
  assert "runtime-secret" not in scope.model_dump_json()


def test_tampered_document_never_reaches_backend() -> None:
  backend = RecordingBackend()
  tools = BasinGraphTools(backend=backend)
  scope = selected_scope().model_copy(update={
    "document_group": (
      DocumentScopeItem(document_id="doc-2", version=3, content_hash=HASH_B),
    ),
  })

  with pytest.raises(ValueError, match="fingerprint"):
    tools.start_basin_graph_build(scope, "service-token")

  assert backend.calls == []


def test_status_and_query_use_the_same_selected_document_scope() -> None:
  backend = RecordingBackend()
  tools = BasinGraphTools(backend=backend)
  scope = selected_scope()

  tools.get_basin_graph_build_status("build-1", scope, "service-token")
  tools.query_basin_graph(scope, basin="红河盆地")

  assert backend.calls == [
    ("status", ("build-1", scope, None)),
    ("query", (scope, None, "红河盆地", None)),
  ]


def test_mcp_exposes_only_the_three_phase_one_tools() -> None:
  mcp = create_mcp(backend=RecordingBackend())

  tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}

  assert tool_names == {
    "start_basin_graph_build",
    "get_basin_graph_build_status",
    "query_basin_graph",
  }


def test_mcp_uses_explicit_http_bind_settings() -> None:
  mcp = create_mcp(
    backend=RecordingBackend(),
    host="0.0.0.0",
    port=9013,
  )

  assert mcp.settings.host == "0.0.0.0"
  assert mcp.settings.port == 9013


def test_start_tool_schema_accepts_router_runtime_provider_config() -> None:
  mcp = create_mcp(backend=RecordingBackend())

  tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

  assert "vlm_config" in tools["start_basin_graph_build"].inputSchema["properties"]
  assert "force_rebuild" in tools["start_basin_graph_build"].inputSchema["properties"]
  assert "vlm_config" in tools["get_basin_graph_build_status"].inputSchema["properties"]


def selected_scope() -> AuthorizedScopeEnvelope:
  unsigned = AuthorizedScopeEnvelope(
    request_id="request-1",
    tenant_id="12",
    requested_by="42",
    project_id="project-1",
    document_group=(
      DocumentScopeItem(document_id="doc-1", version=3, content_hash=HASH_A),
    ),
    extractor_version="g29.1",
  )
  return unsigned.model_copy(update={
    "scope_fingerprint": canonical_scope_fingerprint(unsigned),
  })
