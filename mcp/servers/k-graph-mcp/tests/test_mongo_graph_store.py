from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from k_graph_mcp.graph_store import (
  GraphNotFoundError,
  GraphPublication,
  GraphVersionRecord,
)
from k_graph_mcp.mongo_graph_store import MongoGraphStore


def test_completed_version_lookup_always_uses_tenant_scope_and_terminal_status() -> None:
  store, versions, *_ = fixture()
  versions.find_one.return_value = None

  assert store.completed_version(
    tenant_id="12",
    graph_version_id="graph-1",
    scope_fingerprint="sha256:" + "f" * 64,
  ) is None

  query = versions.find_one.call_args.args[0]
  assert query["tenant_id"] == "12"
  assert query["graph_version_id"] == "graph-1"
  assert query["scope_fingerprint"] == "sha256:" + "f" * 64
  assert set(query["status"]["$in"]) == {
    "COMPLETED",
    "COMPLETED_WITH_GAPS",
  }


def test_empty_staging_payload_becomes_ready_only_after_targeted_writes() -> None:
  store, versions, nodes, edges, evidence, gaps = fixture()
  versions.find_one.return_value = {
    "tenant_id": "12",
    "graph_version_id": "graph-1",
    "status": "STAGING",
  }
  versions.update_one.return_value = SimpleNamespace(matched_count=1)

  store.stage(version(), GraphPublication(
    entities=(),
    relations=(),
    evidence=(),
    gaps=(),
  ), now=now())

  for collection in (nodes, edges, evidence, gaps):
    assert collection.delete_many.call_args.args[0] == {
      "tenant_id": "12",
      "graph_version_id": "graph-1",
    }
  update_filter = versions.update_one.call_args.args[0]
  update = versions.update_one.call_args.args[1]
  assert update_filter == {
    "tenant_id": "12",
    "graph_version_id": "graph-1",
    "status": "STAGING",
  }
  assert update["$set"]["staging_data_ready"] is True


def test_load_never_reads_collections_for_unpublished_version() -> None:
  store, versions, nodes, edges, evidence, gaps = fixture()
  versions.find_one.return_value = None

  with pytest.raises(GraphNotFoundError):
    store.load(version())

  for collection in (nodes, edges, evidence, gaps):
    collection.find.assert_not_called()


def fixture():
  collections = [MagicMock() for _ in range(5)]
  return (
    MongoGraphStore(
      versions=collections[0],
      nodes=collections[1],
      edges=collections[2],
      evidence=collections[3],
      gaps=collections[4],
    ),
    *collections,
  )


def version():
  return GraphVersionRecord(
    graph_version_id="graph-1",
    tenant_id="12",
    build_id="build-1",
    project_id="project-1",
    scope_fingerprint="sha256:" + "f" * 64,
    document_ids=("doc-1",),
    graph_schema_version="1",
    extractor_version="g29.1",
    normalization_version="docintel-normalized-v1",
    status="STAGING",
    created_at=now(),
  )


def now():
  return datetime(2026, 7, 24, tzinfo=timezone.utc)
