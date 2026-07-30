import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from k_graph_mcp.contracts import (
  AuthorizedScopeEnvelope,
  DocumentScopeItem,
  EvidenceRecord,
  EvidenceSubjectKind,
  GraphEntity,
  GraphEntityType,
  GraphRelation,
  GraphRelationType,
  QueryGraphRequest,
  StartBuildRequest,
  canonical_scope_fingerprint,
  validate_graph_contract,
)


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def scope(
  *,
  tenant_id: str = "tenant-a",
  documents: tuple[DocumentScopeItem, ...] | None = None,
  fingerprint: str | None = None,
  graph_name: str | None = None,
) -> AuthorizedScopeEnvelope:
  document_group = documents if documents is not None else (
    DocumentScopeItem(document_id="doc-1", version=2, content_hash=HASH_A),
  )
  return AuthorizedScopeEnvelope(
    request_id="request-1",
    tenant_id=tenant_id,
    requested_by="member-1",
    project_id="project-1",
    document_group=document_group,
    scope_fingerprint=fingerprint,
    graph_name=graph_name,
  )


def evidence(
  *,
  evidence_id: str,
  subject_kind: EvidenceSubjectKind,
  subject_id: str,
  tenant_id: str = "tenant-a",
  document_id: str = "doc-1",
  version: int = 2,
  content_hash: str = HASH_A,
) -> EvidenceRecord:
  return EvidenceRecord(
    evidence_id=evidence_id,
    tenant_id=tenant_id,
    graph_version_id="version-1",
    document_id=document_id,
    document_version=version,
    document_content_hash=content_hash,
    page_no=3,
    chunk_id="chunk-3",
    source_locator="doc-1/v2/page/3#chunk-3",
    bounded_quote="红河盆地由甲凹陷组成。",
    subject_kind=subject_kind,
    subject_id=subject_id,
  )


def test_scope_fingerprint_is_order_independent() -> None:
  first = DocumentScopeItem(document_id="doc-1", version=2, content_hash=HASH_A)
  second = DocumentScopeItem(document_id="doc-2", version=7, content_hash=HASH_B)

  assert canonical_scope_fingerprint(scope(documents=(first, second))) == (
    canonical_scope_fingerprint(scope(documents=(second, first)))
  )


def test_graph_display_name_is_metadata_not_fingerprint_input() -> None:
  assert canonical_scope_fingerprint(scope(graph_name=None)) == (
    canonical_scope_fingerprint(scope(graph_name="Test 4 — Knowledge Graph"))
  )


def test_document_names_are_bounded_metadata_not_fingerprint_input() -> None:
  named = scope().model_copy(update={"document_names": {"doc-1": "Basin report"}})

  assert canonical_scope_fingerprint(named) == canonical_scope_fingerprint(scope())

  with pytest.raises(ValidationError, match="document_names"):
    AuthorizedScopeEnvelope.model_validate({
      **scope().model_dump(mode="json"),
      "document_names": {"outside-scope": "Other report"},
    })


def test_scope_rejects_empty_or_duplicate_documents() -> None:
  with pytest.raises(ValidationError, match="at least 1"):
    scope(documents=())

  duplicate = DocumentScopeItem(document_id="doc-1", version=3, content_hash=HASH_B)
  with pytest.raises(ValidationError, match="duplicate document IDs"):
    scope(documents=(
      DocumentScopeItem(document_id="doc-1", version=2, content_hash=HASH_A),
      duplicate,
    ))


def test_scope_rejects_tampered_fingerprint() -> None:
  with pytest.raises(ValidationError, match="does not match"):
    scope(fingerprint="sha256:" + "0" * 64)


def test_start_requires_membership_fingerprint() -> None:
  unsigned = scope()
  with pytest.raises(ValidationError, match="Membership must provide"):
    StartBuildRequest(scope=unsigned)

  selected = selected_scope()
  request = StartBuildRequest(scope=selected)

  assert request.scope_fingerprint == selected.scope_fingerprint


def test_java_and_python_scope_fingerprint_vectors_match() -> None:
  selected = selected_scope()

  assert selected.scope_fingerprint == (
    "sha256:9cdb65a231875108bf4a8218753a5f292ffabd3c953f61fd1bebd29670791502"
  )


def test_graph_contract_accepts_basin_has_part_sag_with_evidence() -> None:
  entities = (
    GraphEntity(
      entity_id="basin-1",
      entity_type=GraphEntityType.BASIN,
      original_mention="红河盆地",
      display_name="红河盆地",
      evidence_ids=("entity-evidence-basin",),
    ),
    GraphEntity(
      entity_id="sag-1",
      entity_type=GraphEntityType.SAG,
      original_mention="甲凹陷",
      display_name="甲凹陷",
      evidence_ids=("entity-evidence-sag",),
    ),
  )
  relations = (
    GraphRelation(
      relation_id="relation-1",
      source_entity_id="basin-1",
      relation_type=GraphRelationType.HAS_PART,
      target_entity_id="sag-1",
      evidence_ids=("relation-evidence",),
    ),
  )
  records = (
    evidence(
      evidence_id="entity-evidence-basin",
      subject_kind=EvidenceSubjectKind.ENTITY,
      subject_id="basin-1",
    ),
    evidence(
      evidence_id="entity-evidence-sag",
      subject_kind=EvidenceSubjectKind.ENTITY,
      subject_id="sag-1",
    ),
    evidence(
      evidence_id="relation-evidence",
      subject_kind=EvidenceSubjectKind.RELATION,
      subject_id="relation-1",
    ),
  )

  validate_graph_contract(
    entities=entities,
    relations=relations,
    evidence=records,
  )


def test_graph_contract_rejects_wrong_relation_direction() -> None:
  entities = (
    GraphEntity(
      entity_id="basin-1",
      entity_type=GraphEntityType.BASIN,
      original_mention="红河盆地",
      display_name="红河盆地",
      evidence_ids=("basin-evidence",),
    ),
    GraphEntity(
      entity_id="sag-1",
      entity_type=GraphEntityType.SAG,
      original_mention="甲凹陷",
      display_name="甲凹陷",
      evidence_ids=("sag-evidence",),
    ),
  )
  relation = GraphRelation(
    relation_id="relation-1",
    source_entity_id="sag-1",
    relation_type=GraphRelationType.HAS_PART,
    target_entity_id="basin-1",
    evidence_ids=("relation-evidence",),
  )
  records = (
    evidence(
      evidence_id="basin-evidence",
      subject_kind=EvidenceSubjectKind.ENTITY,
      subject_id="basin-1",
    ),
    evidence(
      evidence_id="sag-evidence",
      subject_kind=EvidenceSubjectKind.ENTITY,
      subject_id="sag-1",
    ),
    evidence(
      evidence_id="relation-evidence",
      subject_kind=EvidenceSubjectKind.RELATION,
      subject_id="relation-1",
    ),
  )

  with pytest.raises(ValueError, match="source must be a BASIN"):
    validate_graph_contract(
      entities=entities,
      relations=(relation,),
      evidence=records,
    )


def test_query_requires_basin_or_target() -> None:
  with pytest.raises(ValidationError, match="either basin or target"):
    QueryGraphRequest(
      scope=selected_scope(),
    )


def test_acceptance_corpus_freezes_required_scenarios() -> None:
  fixture = Path(__file__).parent / "fixtures" / "acceptance_corpus.json"
  payload = json.loads(fixture.read_text(encoding="utf-8"))
  scenarios = {item["id"]: item for item in payload["scenarios"]}

  assert set(scenarios) == {
    "positive_basin_child_relation",
    "unsupported_cooccurrence",
    "ambiguous_parent_relation",
    "no_child_in_selected_sources",
    "overlapping_name_tenant_a",
    "overlapping_name_tenant_b",
  }
  assert scenarios["unsupported_cooccurrence"]["expected"]["relations"] == []
  assert scenarios["ambiguous_parent_relation"]["expected"]["relations"] == []
  assert (
    scenarios["overlapping_name_tenant_a"]["tenant_id"]
    != scenarios["overlapping_name_tenant_b"]["tenant_id"]
  )


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
  fingerprint = canonical_scope_fingerprint(unsigned)
  return unsigned.model_copy(update={
    "scope_fingerprint": fingerprint,
  })
