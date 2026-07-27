"""Frozen G29.0 request, scope, graph, and evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ContractModel(BaseModel):
  model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class BuildStatus(StrEnum):
  QUEUED = "QUEUED"
  RUNNING = "RUNNING"
  COMPLETED = "COMPLETED"
  COMPLETED_WITH_GAPS = "COMPLETED_WITH_GAPS"
  FAILED = "FAILED"
  CANCELLED = "CANCELLED"
  PAUSED_AUTH_REQUIRED = "PAUSED_AUTH_REQUIRED"


class GraphEntityType(StrEnum):
  BASIN = "BASIN"
  SAG = "SAG"
  DEPRESSION = "DEPRESSION"


class GraphRelationType(StrEnum):
  HAS_PART = "HAS_PART"


class EvidenceSubjectKind(StrEnum):
  ENTITY = "ENTITY"
  RELATION = "RELATION"


class DocumentScopeItem(ContractModel):
  document_id: str = Field(min_length=1)
  version: int = Field(ge=1)
  content_hash: str

  @field_validator("content_hash")
  @classmethod
  def validate_content_hash(cls, value: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
      raise ValueError("content_hash must be sha256 followed by 64 lowercase hex characters")
    return value


class AuthorizedScopeEnvelope(ContractModel):
  request_id: str = Field(min_length=1)
  tenant_id: str = Field(min_length=1)
  requested_by: str = Field(min_length=1)
  project_id: str | None = None
  document_group: tuple[DocumentScopeItem, ...] = Field(min_length=1)
  graph_schema_version: str = Field(default="1", min_length=1)
  extractor_version: str = Field(default="g29.1", min_length=1)
  normalization_version: str = Field(default="docintel-normalized-v1", min_length=1)
  scope_fingerprint: str | None = None
  graph_name: str | None = Field(default=None, min_length=1, max_length=512)

  @model_validator(mode="after")
  def validate_scope(self) -> "AuthorizedScopeEnvelope":
    document_ids = [item.document_id for item in self.document_group]
    if len(document_ids) != len(set(document_ids)):
      raise ValueError("document_group must not contain duplicate document IDs")
    expected = canonical_scope_fingerprint(self)
    if self.scope_fingerprint is not None and self.scope_fingerprint != expected:
      raise ValueError("scope_fingerprint does not match the authorized scope")
    return self


def canonical_scope_fingerprint(envelope: AuthorizedScopeEnvelope) -> str:
  payload = {
    "tenant_id": envelope.tenant_id,
    "project_id": envelope.project_id or "",
    "documents": [
      {
        "document_id": item.document_id,
        "version": item.version,
        "content_hash": item.content_hash,
      }
      for item in sorted(
        envelope.document_group,
        key=lambda item: (item.document_id, item.version, item.content_hash),
      )
    ],
    "graph_schema_version": envelope.graph_schema_version,
    "extractor_version": envelope.extractor_version,
    "normalization_version": envelope.normalization_version,
  }
  encoded = json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
  ).encode("utf-8")
  return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class StartBuildRequest(ContractModel):
  scope: AuthorizedScopeEnvelope

  @model_validator(mode="after")
  def require_membership_fingerprint(self) -> "StartBuildRequest":
    if self.scope.scope_fingerprint is None:
      raise ValueError("Membership must provide the authorized scope fingerprint")
    return self

  @property
  def scope_fingerprint(self) -> str:
    return canonical_scope_fingerprint(self.scope)


class GetBuildStatusRequest(ContractModel):
  build_id: str = Field(min_length=1)
  scope: AuthorizedScopeEnvelope


class QueryGraphRequest(ContractModel):
  scope: AuthorizedScopeEnvelope
  graph_version_id: str | None = None
  basin: str | None = None
  target: str | None = None

  @model_validator(mode="after")
  def require_query_target(self) -> "QueryGraphRequest":
    if not self.basin and not self.target:
      raise ValueError("either basin or target is required")
    return self


class EvidenceRecord(ContractModel):
  evidence_id: str = Field(min_length=1)
  tenant_id: str = Field(min_length=1)
  graph_version_id: str = Field(min_length=1)
  document_id: str = Field(min_length=1)
  document_version: int = Field(ge=1)
  document_content_hash: str
  page_no: int = Field(ge=1)
  chunk_id: str | None = None
  source_locator: str = Field(min_length=1)
  bounded_quote: str = Field(min_length=1, max_length=2000)
  subject_kind: EvidenceSubjectKind
  subject_id: str = Field(min_length=1)

  @field_validator("document_content_hash")
  @classmethod
  def validate_content_hash(cls, value: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
      raise ValueError("document_content_hash must be a sha256 value")
    return value


class GraphEntity(ContractModel):
  entity_id: str = Field(min_length=1)
  entity_type: GraphEntityType
  original_mention: str = Field(min_length=1)
  display_name: str = Field(min_length=1)
  aliases: tuple[str, ...] = ()
  evidence_ids: tuple[str, ...] = Field(min_length=1)


class GraphRelation(ContractModel):
  relation_id: str = Field(min_length=1)
  source_entity_id: str = Field(min_length=1)
  relation_type: GraphRelationType
  target_entity_id: str = Field(min_length=1)
  evidence_ids: tuple[str, ...] = Field(min_length=1)


def validate_graph_contract(
  *,
  entities: tuple[GraphEntity, ...],
  relations: tuple[GraphRelation, ...],
  evidence: tuple[EvidenceRecord, ...],
) -> None:
  entity_by_id = {item.entity_id: item for item in entities}
  if len(entity_by_id) != len(entities):
    raise ValueError("entity IDs must be unique")

  evidence_by_id = {item.evidence_id: item for item in evidence}
  if len(evidence_by_id) != len(evidence):
    raise ValueError("evidence IDs must be unique")
  for entity in entities:
    _require_evidence(entity.evidence_ids, evidence_by_id, "entity", entity.entity_id)
    for evidence_id in entity.evidence_ids:
      item = evidence_by_id[evidence_id]
      if item.subject_kind != EvidenceSubjectKind.ENTITY or item.subject_id != entity.entity_id:
        raise ValueError("entity evidence subject does not match the entity")

  relation_ids: set[str] = set()
  for relation in relations:
    if relation.relation_id in relation_ids:
      raise ValueError("relation IDs must be unique")
    relation_ids.add(relation.relation_id)
    source = entity_by_id.get(relation.source_entity_id)
    target = entity_by_id.get(relation.target_entity_id)
    if source is None or target is None:
      raise ValueError("relation endpoints must exist")
    if source.entity_type != GraphEntityType.BASIN:
      raise ValueError("HAS_PART source must be a BASIN")
    if target.entity_type not in {GraphEntityType.SAG, GraphEntityType.DEPRESSION}:
      raise ValueError("HAS_PART target must be a SAG or DEPRESSION")
    _require_evidence(
      relation.evidence_ids,
      evidence_by_id,
      "relation",
      relation.relation_id,
    )
    for evidence_id in relation.evidence_ids:
      item = evidence_by_id[evidence_id]
      if item.subject_kind != EvidenceSubjectKind.RELATION or item.subject_id != relation.relation_id:
        raise ValueError("relation evidence subject does not match the relation")


def _require_evidence(
  evidence_ids: tuple[str, ...],
  evidence_by_id: dict[str, EvidenceRecord],
  subject_kind: str,
  subject_id: str,
) -> None:
  missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_by_id]
  if missing:
    raise ValueError(f"{subject_kind} {subject_id} references unknown evidence: {missing}")
