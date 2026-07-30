from datetime import datetime, timezone

import pytest

from k_graph_mcp.contracts import (
  AuthorizedScopeEnvelope,
  BuildStatus,
  DocumentScopeItem,
  canonical_scope_fingerprint,
)
from k_graph_mcp.graph_store import (
  GraphNotFoundError,
  GraphPublisher,
  GraphQueryService,
  InMemoryGraphStore,
)
from k_graph_mcp.lifecycle import BuildOutcome, BuildRecord


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def test_staging_graph_is_invisible_until_atomic_publication() -> None:
  store = InMemoryGraphStore()
  publisher = GraphPublisher(store=store)
  build = build_record()

  version = store.begin_or_reset(build, now=now())
  store.stage(
    version,
    publisher.prepare(build, version.graph_version_id),
    now=now(),
  )

  result = GraphQueryService(store=store).query(
    authorized_scope(),
    graph_version_id=None,
    basin="红河盆地",
    target=None,
  )

  assert result["status"] == "NOT_BUILT"
  assert result["entities"] == []

  published = publisher.publish(build, BuildOutcome.COMPLETED)
  result = GraphQueryService(store=store).query(
    authorized_scope(),
    graph_version_id=None,
    basin="红河盆地",
    target=None,
  )

  assert result["graph_version_id"] == published
  assert result["status"] == "COMPLETED"
  assert result["stale"] is False


def test_query_by_basin_or_target_returns_directed_relation_and_evidence() -> None:
  store = InMemoryGraphStore()
  version_id = GraphPublisher(store=store).publish(
    build_record(),
    BuildOutcome.COMPLETED,
  )
  service = GraphQueryService(store=store)

  by_basin = service.query(
    authorized_scope(),
    graph_version_id=None,
    basin="红河盆地",
    target=None,
  )
  by_target = service.query(
    authorized_scope(),
    graph_version_id=version_id,
    basin=None,
    target="北部凹陷",
  )

  assert [item["display_name"] for item in by_basin["entities"]] == [
    "北部凹陷",
    "红河盆地",
  ]
  assert by_basin["relations"][0]["relation_type"] == "HAS_PART"
  assert len(by_basin["evidence"]) == 3
  assert by_target["relations"] == by_basin["relations"]
  assert by_target["scope_fingerprint"] == authorized_scope().scope_fingerprint


def test_explicit_version_never_crosses_tenant_or_scope() -> None:
  store = InMemoryGraphStore()
  version_id = GraphPublisher(store=store).publish(
    build_record(),
    BuildOutcome.COMPLETED,
  )
  service = GraphQueryService(store=store)

  with pytest.raises(GraphNotFoundError):
    service.query(
      authorized_scope(tenant_id="99"),
      graph_version_id=version_id,
      basin="红河盆地",
      target=None,
    )
  with pytest.raises(GraphNotFoundError):
    service.query(
      authorized_scope(content_hash=HASH_B),
      graph_version_id=version_id,
      basin="红河盆地",
      target=None,
    )


def test_failed_rebuild_never_replaces_last_completed_version() -> None:
  store = InMemoryGraphStore()
  publisher = GraphPublisher(store=store)
  completed = publisher.publish(build_record(), BuildOutcome.COMPLETED)
  failed_build = build_record(build_id="build-2")
  staging = store.begin_or_reset(failed_build, now=now())
  store.stage(
    staging,
    publisher.prepare(failed_build, staging.graph_version_id),
    now=now(),
  )
  store.fail(staging, error_code="WRITE_FAILED", now=now())

  result = GraphQueryService(store=store).query(
    authorized_scope(),
    graph_version_id=None,
    basin="红河盆地",
    target=None,
  )

  assert result["graph_version_id"] == completed


def test_changed_document_hash_reports_stale_without_reusing_old_graph() -> None:
  store = InMemoryGraphStore()
  GraphPublisher(store=store).publish(
    build_record(),
    BuildOutcome.COMPLETED,
  )

  result = GraphQueryService(store=store).query(
    authorized_scope(content_hash=HASH_B),
    graph_version_id=None,
    basin="红河盆地",
    target=None,
  )

  assert result == {
    "status": "NOT_BUILT",
    "graph_version_id": None,
    "scope_fingerprint": authorized_scope(
      content_hash=HASH_B
    ).scope_fingerprint,
    "stale": True,
    "entities": [],
    "relations": [],
    "evidence": [],
    "gaps": [],
  }


def test_publication_preserves_structured_gap_context_for_expert_review() -> None:
  build = build_record()
  payload = publication_payload()
  payload["gaps"] = [{
    "code": "REJECTED_EXTRACTION_CANDIDATE",
    "description": "relations.evidence_quote: missing_relation_mentions",
    "evidence_quote": "红河盆地发育北部凹陷",
    "document_id": "doc-1",
    "document_version": 3,
    "page_no": 1,
    "source_locator": "document:doc-1/version:3/page:1/chunk:chunk-1/segment:0",
    "subject_kind": "RELATION",
    "candidate": "红河盆地 → 北部凹陷",
    "field": "relations.evidence_quote",
    "issue": "missing_relation_mentions",
  }]
  build.checkpoint_results["doc-1/v3/p1/chunk-1/s0"] = payload

  gap = GraphPublisher(store=InMemoryGraphStore()).prepare(build, "graph-1").gaps[0]

  assert gap.document_id == "doc-1"
  assert gap.document_version == 3
  assert gap.page_no == 1
  assert gap.subject_kind == "RELATION"
  assert gap.candidate == "红河盆地 → 北部凹陷"
  assert gap.field == "relations.evidence_quote"
  assert gap.issue == "missing_relation_mentions"


def build_record(build_id: str = "build-1") -> BuildRecord:
  scope = authorized_scope()
  return BuildRecord(
    build_id=build_id,
    tenant_id=scope.tenant_id,
    scope_fingerprint=scope.scope_fingerprint,
    request_id="request-1",
    requested_by="42",
    project_id="project-1",
    source_scope={
      "tenant_id": scope.tenant_id,
      "project_id": scope.project_id,
      "document_group": [
        item.model_dump(mode="json") for item in scope.document_group
      ],
      "graph_schema_version": scope.graph_schema_version,
      "extractor_version": scope.extractor_version,
      "normalization_version": scope.normalization_version,
    },
    status=BuildStatus.RUNNING,
    phase="BUILDING",
    attempt=1,
    prior_build_id=None,
    retry_count=0,
    completed_unit_ids=("doc-1/v3/p1/chunk-1/s0",),
    checkpoint_results={
      "doc-1/v3/p1/chunk-1/s0": publication_payload(),
    },
    cancel_requested=False,
    lease_owner="worker-1",
    lease_expires_at=now(),
    lease_reclaims=0,
    next_attempt_at=now(),
    created_at=now(),
    updated_at=now(),
  )


def publication_payload():
  basin_key = "entity-basin"
  child_key = "entity-child"
  relation_key = "relation-1"
  return {
    "entities": [
      {
        "entity_key": basin_key,
        "entity_type": "BASIN",
        "original_mention": "红河盆地",
        "display_name": "红河盆地",
        "aliases": [],
      },
      {
        "entity_key": child_key,
        "entity_type": "DEPRESSION",
        "original_mention": "北部凹陷",
        "display_name": "北部凹陷",
        "aliases": [],
      },
    ],
    "relations": [{
      "relation_key": relation_key,
      "source_entity_key": basin_key,
      "source_entity_type": "BASIN",
      "relation_type": "HAS_PART",
      "target_entity_key": child_key,
      "target_entity_type": "DEPRESSION",
    }],
    "evidence": [
      evidence("ev-basin", "ENTITY", basin_key),
      evidence("ev-child", "ENTITY", child_key),
      evidence("ev-relation", "RELATION", relation_key),
    ],
    "gaps": [],
  }


def evidence(evidence_key, subject_kind, subject_key):
  return {
    "evidence_key": evidence_key,
    "document_id": "doc-1",
    "document_version": 3,
    "document_content_hash": HASH_A,
    "page_no": 1,
    "chunk_id": "chunk-1",
    "source_locator": "document:doc-1/version:3/page:1/chunk:chunk-1",
    "bounded_quote": "红河盆地包括北部凹陷",
    "subject_kind": subject_kind,
    "subject_key": subject_key,
  }


def authorized_scope(
  *,
  tenant_id: str = "12",
  content_hash: str = HASH_A,
) -> AuthorizedScopeEnvelope:
  unsigned = AuthorizedScopeEnvelope(
    request_id="request-1",
    tenant_id=tenant_id,
    requested_by="42",
    project_id="project-1",
    document_group=(
      DocumentScopeItem(
        document_id="doc-1",
        version=3,
        content_hash=content_hash,
      ),
    ),
  )
  return unsigned.model_copy(update={
    "scope_fingerprint": canonical_scope_fingerprint(unsigned),
  })


def now():
  return datetime(2026, 7, 24, tzinfo=timezone.utc)
