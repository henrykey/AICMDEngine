from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from k_graph_mcp.contracts import (
  AuthorizedScopeEnvelope,
  DocumentScopeItem,
  canonical_scope_fingerprint,
)
from k_graph_mcp.lifecycle import BuildNotFoundError
from k_graph_mcp.mongo_repository import MongoBuildRepository


HASH_A = "sha256:" + "a" * 64


def test_indexes_enforce_one_reusable_build_per_tenant_scope() -> None:
  collection = MagicMock()

  MongoBuildRepository(collection).ensure_indexes()

  assert collection.create_index.call_args_list[0] == call(
    [("tenant_id", 1), ("build_id", 1)],
    unique=True,
    name="tenant_build_unique",
  )
  assert collection.create_index.call_args_list[1] == call(
    [("tenant_id", 1), ("scope_fingerprint", 1)],
    unique=True,
    partialFilterExpression={"reusable": True},
    name="tenant_scope_reusable_unique",
  )


def test_new_build_persists_only_the_frozen_selected_document_scope() -> None:
  collection = MagicMock()
  collection.find_one.side_effect = [None, None]
  repository = MongoBuildRepository(collection)
  authorized = scope()

  created = repository.start_or_reuse(
    authorized,
    now=datetime(2026, 7, 24, tzinfo=timezone.utc),
  )

  inserted = collection.insert_one.call_args.args[0]
  assert created.tenant_id == "12"
  assert inserted["source_scope"]["document_group"] == [{
    "document_id": "doc-1",
    "version": 3,
    "content_hash": HASH_A,
  }]
  assert set(inserted["source_scope"]) == {
    "tenant_id",
    "project_id",
    "document_group",
    "graph_schema_version",
    "extractor_version",
    "normalization_version",
  }


def test_worker_claim_and_stale_failure_are_tenant_scoped() -> None:
  collection = MagicMock()
  collection.find_one_and_update.side_effect = [None, None]
  collection.update_one.return_value = SimpleNamespace(
    matched_count=0,
    modified_count=0,
  )
  repository = MongoBuildRepository(collection)

  assert repository.claim(
    "build-1",
    tenant_id="12",
    worker_id="worker-1",
    now=datetime(2026, 7, 24, tzinfo=timezone.utc),
    lease_duration=timedelta(seconds=30),
  ) is None

  for operation in collection.find_one_and_update.call_args_list:
    assert operation.args[0]["tenant_id"] == "12"
    assert operation.args[0]["build_id"] == "build-1"
  stale_failure_filter = collection.update_one.call_args.args[0]
  assert stale_failure_filter["tenant_id"] == "12"
  assert stale_failure_filter["build_id"] == "build-1"


def test_status_scope_mismatch_does_not_probe_by_global_build_id() -> None:
  collection = MagicMock()
  collection.find_one.return_value = None
  repository = MongoBuildRepository(collection)

  with pytest.raises(BuildNotFoundError):
    repository.get_for_scope(
      "build-1",
      tenant_id="99",
      scope_fingerprint="sha256:" + "f" * 64,
    )

  assert collection.find_one.call_args.args[0] == {
    "tenant_id": "99",
    "build_id": "build-1",
    "scope_fingerprint": "sha256:" + "f" * 64,
  }


def test_failure_persists_bounded_extraction_diagnostic() -> None:
  collection = MagicMock()
  collection.update_one.return_value = SimpleNamespace(matched_count=1)
  diagnostic = {
    "category": "SCHEMA",
    "field": "entities.0.entity_type",
    "issue": "enum",
    "document_id": "doc-1",
    "document_version": 3,
    "page_no": 1,
    "unit_id": "doc-1/v3/p1/chunk-1/s0",
  }

  MongoBuildRepository(collection).fail(
    "build-1",
    tenant_id="12",
    worker_id="worker-1",
    error_code="EXTRACTION_VALIDATION_FAILED",
    error_diagnostic=diagnostic,
    now=datetime(2026, 7, 24, tzinfo=timezone.utc),
  )

  update = collection.update_one.call_args.args[1]["$set"]
  assert update["error_diagnostic"] == diagnostic


def scope() -> AuthorizedScopeEnvelope:
  unsigned = AuthorizedScopeEnvelope(
    request_id="request-1",
    tenant_id="12",
    requested_by="42",
    project_id="project-1",
    document_group=(
      DocumentScopeItem(document_id="doc-1", version=3, content_hash=HASH_A),
    ),
  )
  return unsigned.model_copy(update={
    "scope_fingerprint": canonical_scope_fingerprint(unsigned),
  })
