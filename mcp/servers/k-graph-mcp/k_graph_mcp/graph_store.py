"""Immutable graph publication and exact-scope query services."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from .contracts import (
  AuthorizedScopeEnvelope,
  EvidenceRecord,
  EvidenceSubjectKind,
  GraphEntity,
  GraphEntityType,
  GraphRelation,
  GraphRelationType,
  validate_graph_contract,
)
from .extraction import ExtractedUnitResult
from .lifecycle import BuildOutcome, BuildRecord


class GraphNotFoundError(LookupError):
  """Missing and unauthorized graph versions intentionally share one error."""


class GraphPublicationError(RuntimeError):
  """Validated checkpoints could not form one immutable graph."""


class GraphModel(BaseModel):
  model_config = ConfigDict(extra="forbid", frozen=True)


class PublishedEntity(GraphModel):
  entity_id: str
  entity_type: GraphEntityType
  original_mention: str
  display_name: str
  aliases: tuple[str, ...]
  evidence_ids: tuple[str, ...]


class PublishedRelation(GraphModel):
  relation_id: str
  source_entity_id: str
  relation_type: GraphRelationType
  target_entity_id: str
  evidence_ids: tuple[str, ...]


class PublishedEvidence(GraphModel):
  evidence_id: str
  document_id: str
  document_version: int
  document_content_hash: str
  page_no: int
  chunk_id: str | None
  source_locator: str
  bounded_quote: str
  subject_kind: EvidenceSubjectKind
  subject_id: str


class PublishedGap(GraphModel):
  unit_id: str
  code: str
  description: str
  evidence_quote: str | None = None
  document_id: str | None = None
  document_version: int | None = None
  page_no: int | None = None
  source_locator: str | None = None
  subject_kind: str | None = None
  candidate: str | None = None
  candidate_text: str | None = None
  field: str | None = None
  issue: str | None = None


class GraphPublication(GraphModel):
  entities: tuple[PublishedEntity, ...]
  relations: tuple[PublishedRelation, ...]
  evidence: tuple[PublishedEvidence, ...]
  gaps: tuple[PublishedGap, ...]


@dataclass(frozen=True)
class GraphVersionRecord:
  graph_version_id: str
  tenant_id: str
  build_id: str
  project_id: str | None
  scope_fingerprint: str
  document_ids: tuple[str, ...]
  graph_schema_version: str
  extractor_version: str
  normalization_version: str
  status: str
  created_at: datetime
  published_at: datetime | None = None
  error_code: str | None = None
  graph_name: str | None = None


class GraphStore(Protocol):
  def begin_or_reset(
    self,
    build: BuildRecord,
    *,
    now: datetime,
  ) -> GraphVersionRecord: ...

  def stage(
    self,
    version: GraphVersionRecord,
    publication: GraphPublication,
    *,
    now: datetime,
  ) -> None: ...

  def publish(
    self,
    version: GraphVersionRecord,
    *,
    outcome: BuildOutcome,
    now: datetime,
  ) -> None: ...

  def fail(
    self,
    version: GraphVersionRecord,
    *,
    error_code: str,
    now: datetime,
  ) -> None: ...

  def latest_completed(
    self,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> GraphVersionRecord | None: ...

  def completed_version(
    self,
    *,
    tenant_id: str,
    graph_version_id: str,
    scope_fingerprint: str,
  ) -> GraphVersionRecord | None: ...

  def has_stale_version(
    self,
    *,
    tenant_id: str,
    project_id: str | None,
    document_ids: tuple[str, ...],
    scope_fingerprint: str,
  ) -> bool: ...

  def load(
    self,
    version: GraphVersionRecord,
  ) -> GraphPublication: ...


class InMemoryGraphStore:
  def __init__(self):
    self._versions: dict[str, GraphVersionRecord] = {}
    self._build_versions: dict[tuple[str, str], str] = {}
    self._data: dict[str, GraphPublication] = {}
    self._lock = threading.RLock()

  def begin_or_reset(
    self,
    build: BuildRecord,
    *,
    now: datetime,
  ) -> GraphVersionRecord:
    with self._lock:
      build_key = (build.tenant_id, build.build_id)
      existing_id = self._build_versions.get(build_key)
      if existing_id is not None:
        existing = self._versions[existing_id]
        if existing.status in _COMPLETED_STATUSES:
          return existing
        version = replace(
          existing,
          status="STAGING",
          published_at=None,
          error_code=None,
          graph_name=build.source_scope.get("graph_name"),
        )
        self._versions[existing_id] = version
        self._data.pop(existing_id, None)
        return version
      scope = build.source_scope
      version = GraphVersionRecord(
        graph_version_id=f"graph-{uuid.uuid4()}",
        tenant_id=build.tenant_id,
        build_id=build.build_id,
        project_id=build.project_id,
        scope_fingerprint=build.scope_fingerprint,
        document_ids=tuple(sorted(
          item["document_id"] for item in scope["document_group"]
        )),
        graph_schema_version=scope["graph_schema_version"],
        extractor_version=scope["extractor_version"],
        normalization_version=scope["normalization_version"],
        status="STAGING",
        created_at=now,
        graph_name=scope.get("graph_name"),
      )
      self._versions[version.graph_version_id] = version
      self._build_versions[build_key] = version.graph_version_id
      return version

  def stage(
    self,
    version: GraphVersionRecord,
    publication: GraphPublication,
    *,
    now: datetime,
  ) -> None:
    with self._lock:
      current = self._versions.get(version.graph_version_id)
      if (
        current is None
        or current.tenant_id != version.tenant_id
        or current.status != "STAGING"
      ):
        raise GraphPublicationError("graph version is not writable staging")
      self._data[version.graph_version_id] = publication

  def publish(
    self,
    version: GraphVersionRecord,
    *,
    outcome: BuildOutcome,
    now: datetime,
  ) -> None:
    with self._lock:
      current = self._versions.get(version.graph_version_id)
      if current is None or current.status != "STAGING":
        raise GraphPublicationError("graph version is not staging")
      if version.graph_version_id not in self._data:
        raise GraphPublicationError("graph version has no staged data")
      self._versions[version.graph_version_id] = replace(
        current,
        status=outcome.value,
        published_at=now,
      )

  def fail(
    self,
    version: GraphVersionRecord,
    *,
    error_code: str,
    now: datetime,
  ) -> None:
    with self._lock:
      current = self._versions.get(version.graph_version_id)
      if current is not None and current.status == "STAGING":
        self._versions[version.graph_version_id] = replace(
          current,
          status="FAILED",
          error_code=error_code,
        )

  def latest_completed(
    self,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> GraphVersionRecord | None:
    with self._lock:
      matches = [
        item for item in self._versions.values()
        if item.tenant_id == tenant_id
        and item.scope_fingerprint == scope_fingerprint
        and item.status in _COMPLETED_STATUSES
      ]
      return max(
        matches,
        key=lambda item: item.published_at or item.created_at,
        default=None,
      )

  def completed_version(
    self,
    *,
    tenant_id: str,
    graph_version_id: str,
    scope_fingerprint: str,
  ) -> GraphVersionRecord | None:
    with self._lock:
      version = self._versions.get(graph_version_id)
      if (
        version is None
        or version.tenant_id != tenant_id
        or version.scope_fingerprint != scope_fingerprint
        or version.status not in _COMPLETED_STATUSES
      ):
        return None
      return version

  def has_stale_version(
    self,
    *,
    tenant_id: str,
    project_id: str | None,
    document_ids: tuple[str, ...],
    scope_fingerprint: str,
  ) -> bool:
    with self._lock:
      return any(
        item.tenant_id == tenant_id
        and item.project_id == project_id
        and item.document_ids == tuple(sorted(document_ids))
        and item.scope_fingerprint != scope_fingerprint
        and item.status in _COMPLETED_STATUSES
        for item in self._versions.values()
      )

  def load(self, version: GraphVersionRecord) -> GraphPublication:
    with self._lock:
      current = self.completed_version(
        tenant_id=version.tenant_id,
        graph_version_id=version.graph_version_id,
        scope_fingerprint=version.scope_fingerprint,
      )
      if current is None:
        raise GraphNotFoundError("graph version not found")
      return self._data[version.graph_version_id]


class GraphPublisher:
  def __init__(
    self,
    *,
    store: GraphStore,
    clock: Any | None = None,
  ):
    self._store = store
    self._clock = clock or (lambda: datetime.now(timezone.utc))

  def publish(
    self,
    build: BuildRecord,
    outcome: BuildOutcome,
  ) -> str:
    version = self._store.begin_or_reset(build, now=self._clock())
    if version.status in _COMPLETED_STATUSES:
      return version.graph_version_id
    try:
      publication = self.prepare(build, version.graph_version_id)
      self._store.stage(version, publication, now=self._clock())
      self._store.publish(version, outcome=outcome, now=self._clock())
      return version.graph_version_id
    except Exception:
      self._store.fail(
        version,
        error_code="GRAPH_PUBLICATION_FAILED",
        now=self._clock(),
      )
      raise

  def prepare(
    self,
    build: BuildRecord,
    graph_version_id: str,
  ) -> GraphPublication:
    results: list[tuple[str, ExtractedUnitResult]] = []
    for unit_id in build.completed_unit_ids:
      value = build.checkpoint_results.get(unit_id)
      if value is None:
        raise GraphPublicationError(
          f"completed unit has no validated checkpoint: {unit_id}"
        )
      results.append((unit_id, ExtractedUnitResult.model_validate(value)))

    entity_values: dict[str, list[Any]] = {}
    relation_values: dict[str, Any] = {}
    evidence_values: dict[str, Any] = {}
    gaps: list[PublishedGap] = []
    for unit_id, result in results:
      for entity in result.entities:
        matches = entity_values.setdefault(entity.entity_key, [])
        if matches and (
          matches[0].entity_type != entity.entity_type
          or matches[0].display_name != entity.display_name
        ):
          raise GraphPublicationError("conflicting entity checkpoint values")
        matches.append(entity)
      for relation in result.relations:
        prior = relation_values.setdefault(relation.relation_key, relation)
        if prior != relation:
          raise GraphPublicationError("conflicting relation checkpoint values")
      for evidence in result.evidence:
        prior = evidence_values.setdefault(evidence.evidence_key, evidence)
        if prior != evidence:
          raise GraphPublicationError("conflicting evidence checkpoint values")
      gaps.extend(
        PublishedGap(
          unit_id=unit_id,
          code=gap.code,
          description=gap.description,
          evidence_quote=gap.evidence_quote,
          document_id=gap.document_id,
          document_version=gap.document_version,
          page_no=gap.page_no,
          source_locator=gap.source_locator,
          subject_kind=gap.subject_kind,
          candidate=gap.candidate,
          candidate_text=gap.candidate_text,
          field=gap.field or (
            gap.diagnostic.get("field") if gap.diagnostic else None
          ),
          issue=gap.issue or (
            gap.diagnostic.get("issue") if gap.diagnostic else None
          ),
        )
        for gap in result.gaps
      )

    evidence_by_subject: dict[tuple[str, str], list[str]] = {}
    published_evidence: list[PublishedEvidence] = []
    for item in evidence_values.values():
      evidence_by_subject.setdefault(
        (item.subject_kind, item.subject_key),
        [],
      ).append(item.evidence_key)
      published_evidence.append(PublishedEvidence(
        evidence_id=item.evidence_key,
        document_id=item.document_id,
        document_version=item.document_version,
        document_content_hash=item.document_content_hash,
        page_no=item.page_no,
        chunk_id=item.chunk_id,
        source_locator=item.source_locator,
        bounded_quote=item.bounded_quote,
        subject_kind=EvidenceSubjectKind(item.subject_kind),
        subject_id=item.subject_key,
      ))

    entities = tuple(sorted(
      (
        PublishedEntity(
          entity_id=item.entity_key,
          entity_type=GraphEntityType(item.entity_type),
          original_mention=item.original_mention,
          display_name=item.display_name,
          aliases=tuple(sorted({
            alias
            for match in matches
            for alias in match.aliases
          })),
          evidence_ids=tuple(sorted(
            evidence_by_subject.get(("ENTITY", item.entity_key), [])
          )),
        )
        for matches in entity_values.values()
        for item in matches[:1]
      ),
      key=lambda item: item.entity_id,
    ))
    relations = tuple(sorted(
      (
        PublishedRelation(
          relation_id=item.relation_key,
          source_entity_id=item.source_entity_key,
          relation_type=GraphRelationType(item.relation_type),
          target_entity_id=item.target_entity_key,
          evidence_ids=tuple(sorted(
            evidence_by_subject.get(("RELATION", item.relation_key), [])
          )),
        )
        for item in relation_values.values()
      ),
      key=lambda item: item.relation_id,
    ))
    evidence = tuple(sorted(
      published_evidence,
      key=lambda item: item.evidence_id,
    ))
    _validate_publication(
      build=build,
      graph_version_id=graph_version_id,
      entities=entities,
      relations=relations,
      evidence=evidence,
    )
    return GraphPublication(
      entities=entities,
      relations=relations,
      evidence=evidence,
      gaps=tuple(sorted(
        gaps,
        key=lambda item: (item.unit_id, item.code),
      )),
    )


class GraphQueryService:
  def __init__(self, *, store: GraphStore, build_repository: Any | None = None):
    self._store = store
    self._build_repository = build_repository

  def query(
    self,
    scope: AuthorizedScopeEnvelope,
    *,
    graph_version_id: str | None,
    basin: str | None,
    target: str | None,
  ) -> dict[str, Any]:
    fingerprint = scope.scope_fingerprint
    if fingerprint is None:
      raise ValueError("scope_fingerprint is required")
    if graph_version_id is not None:
      version = self._store.completed_version(
        tenant_id=scope.tenant_id,
        graph_version_id=graph_version_id,
        scope_fingerprint=fingerprint,
      )
      if version is None:
        raise GraphNotFoundError("graph version not found")
    else:
      version = self._store.latest_completed(
        tenant_id=scope.tenant_id,
        scope_fingerprint=fingerprint,
      )
    if version is None:
      stale = self._store.has_stale_version(
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        document_ids=tuple(
          item.document_id for item in scope.document_group
        ),
        scope_fingerprint=fingerprint,
      )
      build = (
        self._build_repository.latest_for_scope(
          tenant_id=scope.tenant_id,
          scope_fingerprint=fingerprint,
        )
        if self._build_repository is not None
        else None
      )
      return _empty_query(fingerprint, stale=stale, build=build)

    publication = self._store.load(version)
    search = (basin or target or "").strip().casefold()
    matched = {
      item.entity_id
      for item in publication.entities
      if (
        basin is None or item.entity_type == GraphEntityType.BASIN
      ) and search in {
        item.display_name.casefold(),
        *(alias.casefold() for alias in item.aliases),
      }
    }
    selected_relations = tuple(
      item for item in publication.relations
      if (
        item.source_entity_id in matched
        or item.target_entity_id in matched
      )
    )
    selected_entities = set(matched)
    for relation in selected_relations:
      selected_entities.add(relation.source_entity_id)
      selected_entities.add(relation.target_entity_id)
    entities = tuple(sorted(
      (
        item for item in publication.entities
        if item.entity_id in selected_entities
      ),
      key=lambda item: item.display_name,
    ))
    subject_ids = {
      *((EvidenceSubjectKind.ENTITY, item.entity_id) for item in entities),
      *((
        EvidenceSubjectKind.RELATION,
        item.relation_id,
      ) for item in selected_relations),
    }
    evidence = tuple(
      item for item in publication.evidence
      if (item.subject_kind, item.subject_id) in subject_ids
    )
    return {
      "status": version.status,
      "graph_version_id": version.graph_version_id,
      "scope_fingerprint": version.scope_fingerprint,
      "stale": False,
      "entities": [
        item.model_dump(mode="json") for item in entities
      ],
      "relations": [
        item.model_dump(mode="json") for item in selected_relations
      ],
      "evidence": [
        item.model_dump(mode="json") for item in evidence
      ],
      "gaps": [
        item.model_dump(mode="json") for item in publication.gaps
      ],
    }


_COMPLETED_STATUSES = {
  BuildOutcome.COMPLETED.value,
  BuildOutcome.COMPLETED_WITH_GAPS.value,
}


def _validate_publication(
  *,
  build: BuildRecord,
  graph_version_id: str,
  entities: tuple[PublishedEntity, ...],
  relations: tuple[PublishedRelation, ...],
  evidence: tuple[PublishedEvidence, ...],
) -> None:
  validate_graph_contract(
    entities=tuple(
      GraphEntity(
        entity_id=item.entity_id,
        entity_type=item.entity_type,
        original_mention=item.original_mention,
        display_name=item.display_name,
        aliases=item.aliases,
        evidence_ids=item.evidence_ids,
      )
      for item in entities
    ),
    relations=tuple(
      GraphRelation(
        relation_id=item.relation_id,
        source_entity_id=item.source_entity_id,
        relation_type=item.relation_type,
        target_entity_id=item.target_entity_id,
        evidence_ids=item.evidence_ids,
      )
      for item in relations
    ),
    evidence=tuple(
      EvidenceRecord(
        evidence_id=item.evidence_id,
        tenant_id=build.tenant_id,
        graph_version_id=graph_version_id,
        document_id=item.document_id,
        document_version=item.document_version,
        document_content_hash=item.document_content_hash,
        page_no=item.page_no,
        chunk_id=item.chunk_id,
        source_locator=item.source_locator,
        bounded_quote=item.bounded_quote,
        subject_kind=item.subject_kind,
        subject_id=item.subject_id,
      )
      for item in evidence
    ),
  )


def _empty_query(
  fingerprint: str,
  *,
  stale: bool,
  build: BuildRecord | None = None,
) -> dict[str, Any]:
  result = {
    "status": "NOT_BUILT",
    "graph_version_id": None,
    "scope_fingerprint": fingerprint,
    "stale": stale,
    "entities": [],
    "relations": [],
    "evidence": [],
    "gaps": [],
  }
  if build is not None:
    result.update({
      "build_id": build.build_id,
      "build_status": build.status.value,
      "build_error_code": build.error_code,
    })
  return result
