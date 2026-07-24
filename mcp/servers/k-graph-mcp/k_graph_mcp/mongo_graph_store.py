"""MongoDB storage for immutable BasinComparator graph versions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from .graph_store import (
  GraphNotFoundError,
  GraphPublication,
  GraphPublicationError,
  GraphVersionRecord,
  PublishedEntity,
  PublishedEvidence,
  PublishedGap,
  PublishedRelation,
  _COMPLETED_STATUSES,
)
from .lifecycle import BuildOutcome, BuildRecord


class MongoGraphStore:
  def __init__(
    self,
    *,
    versions: Collection,
    nodes: Collection,
    edges: Collection,
    evidence: Collection,
    gaps: Collection,
  ):
    self._versions = versions
    self._nodes = nodes
    self._edges = edges
    self._evidence = evidence
    self._gaps = gaps

  def ensure_indexes(self) -> None:
    self._versions.create_index(
      [("tenant_id", ASCENDING), ("graph_version_id", ASCENDING)],
      unique=True,
      name="tenant_graph_version_unique",
    )
    self._versions.create_index(
      [("tenant_id", ASCENDING), ("build_id", ASCENDING)],
      unique=True,
      name="tenant_build_graph_unique",
    )
    self._versions.create_index(
      [
        ("tenant_id", ASCENDING),
        ("scope_fingerprint", ASCENDING),
        ("status", ASCENDING),
        ("published_at", DESCENDING),
      ],
      name="tenant_scope_completed",
    )
    self._versions.create_index(
      [
        ("tenant_id", ASCENDING),
        ("project_id", ASCENDING),
        ("document_ids", ASCENDING),
        ("status", ASCENDING),
      ],
      name="tenant_documents_staleness",
    )
    self._nodes.create_index(
      [
        ("tenant_id", ASCENDING),
        ("graph_version_id", ASCENDING),
        ("entity_id", ASCENDING),
      ],
      unique=True,
      name="tenant_version_entity_unique",
    )
    self._nodes.create_index(
      [
        ("tenant_id", ASCENDING),
        ("graph_version_id", ASCENDING),
        ("display_name", ASCENDING),
      ],
      name="tenant_version_entity_name",
    )
    self._edges.create_index(
      [
        ("tenant_id", ASCENDING),
        ("graph_version_id", ASCENDING),
        ("relation_id", ASCENDING),
      ],
      unique=True,
      name="tenant_version_relation_unique",
    )
    self._evidence.create_index(
      [
        ("tenant_id", ASCENDING),
        ("graph_version_id", ASCENDING),
        ("evidence_id", ASCENDING),
      ],
      unique=True,
      name="tenant_version_evidence_unique",
    )
    self._gaps.create_index(
      [
        ("tenant_id", ASCENDING),
        ("graph_version_id", ASCENDING),
        ("unit_id", ASCENDING),
        ("code", ASCENDING),
      ],
      name="tenant_version_gap",
    )

  def begin_or_reset(
    self,
    build: BuildRecord,
    *,
    now: datetime,
  ) -> GraphVersionRecord:
    identity = {
      "tenant_id": build.tenant_id,
      "build_id": build.build_id,
    }
    existing = self._versions.find_one(identity)
    if existing is not None:
      version = _version(existing)
      if version.status in _COMPLETED_STATUSES:
        return version
      self._clear_staging(build.tenant_id, version.graph_version_id)
      reset = self._versions.find_one_and_update(
        identity,
        {
          "$set": {
            "status": "STAGING",
            "published_at": None,
            "error_code": None,
            "staging_data_ready": False,
            "updated_at": now,
          }
        },
        return_document=ReturnDocument.AFTER,
      )
      return _version(reset)

    document = {
      "tenant_id": build.tenant_id,
      "graph_version_id": f"graph-{__import__('uuid').uuid4()}",
      "build_id": build.build_id,
      "project_id": build.project_id,
      "scope_fingerprint": build.scope_fingerprint,
      "document_ids": sorted(
        item["document_id"]
        for item in build.source_scope["document_group"]
      ),
      "graph_schema_version": build.source_scope["graph_schema_version"],
      "extractor_version": build.source_scope["extractor_version"],
      "normalization_version": build.source_scope["normalization_version"],
      "status": "STAGING",
      "staging_data_ready": False,
      "created_at": now,
      "updated_at": now,
      "published_at": None,
      "error_code": None,
    }
    try:
      self._versions.insert_one(document)
      return _version(document)
    except DuplicateKeyError:
      raced = self._versions.find_one(identity)
      if raced is None:
        raise
      return _version(raced)

  def stage(
    self,
    version: GraphVersionRecord,
    publication: GraphPublication,
    *,
    now: datetime,
  ) -> None:
    writable = self._versions.find_one({
      "tenant_id": version.tenant_id,
      "graph_version_id": version.graph_version_id,
      "status": "STAGING",
    })
    if writable is None:
      raise GraphPublicationError("graph version is not writable staging")
    self._clear_staging(version.tenant_id, version.graph_version_id)
    common = {
      "tenant_id": version.tenant_id,
      "graph_version_id": version.graph_version_id,
    }
    if publication.entities:
      self._nodes.insert_many([
        {
          **common,
          **item.model_dump(mode="json"),
        }
        for item in publication.entities
      ])
    if publication.relations:
      self._edges.insert_many([
        {
          **common,
          **item.model_dump(mode="json"),
        }
        for item in publication.relations
      ])
    if publication.evidence:
      self._evidence.insert_many([
        {
          **common,
          **item.model_dump(mode="json"),
        }
        for item in publication.evidence
      ])
    if publication.gaps:
      self._gaps.insert_many([
        {
          **common,
          **item.model_dump(mode="json"),
        }
        for item in publication.gaps
      ])
    result = self._versions.update_one(
      {
        "tenant_id": version.tenant_id,
        "graph_version_id": version.graph_version_id,
        "status": "STAGING",
      },
      {
        "$set": {
          "staging_data_ready": True,
          "entity_count": len(publication.entities),
          "relation_count": len(publication.relations),
          "evidence_count": len(publication.evidence),
          "gap_count": len(publication.gaps),
          "updated_at": now,
        }
      },
    )
    if not result.matched_count:
      raise GraphPublicationError("graph staging lease changed")

  def publish(
    self,
    version: GraphVersionRecord,
    *,
    outcome: BuildOutcome,
    now: datetime,
  ) -> None:
    result = self._versions.update_one(
      {
        "tenant_id": version.tenant_id,
        "graph_version_id": version.graph_version_id,
        "status": "STAGING",
        "staging_data_ready": True,
      },
      {
        "$set": {
          "status": outcome.value,
          "published_at": now,
          "updated_at": now,
        }
      },
    )
    if not result.matched_count:
      raise GraphPublicationError("graph publication precondition failed")

  def fail(
    self,
    version: GraphVersionRecord,
    *,
    error_code: str,
    now: datetime,
  ) -> None:
    self._versions.update_one(
      {
        "tenant_id": version.tenant_id,
        "graph_version_id": version.graph_version_id,
        "status": "STAGING",
      },
      {
        "$set": {
          "status": "FAILED",
          "error_code": error_code,
          "updated_at": now,
        }
      },
    )

  def latest_completed(
    self,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> GraphVersionRecord | None:
    document = self._versions.find_one(
      {
        "tenant_id": tenant_id,
        "scope_fingerprint": scope_fingerprint,
        "status": {"$in": sorted(_COMPLETED_STATUSES)},
      },
      sort=[("published_at", DESCENDING)],
    )
    return None if document is None else _version(document)

  def completed_version(
    self,
    *,
    tenant_id: str,
    graph_version_id: str,
    scope_fingerprint: str,
  ) -> GraphVersionRecord | None:
    document = self._versions.find_one({
      "tenant_id": tenant_id,
      "graph_version_id": graph_version_id,
      "scope_fingerprint": scope_fingerprint,
      "status": {"$in": sorted(_COMPLETED_STATUSES)},
    })
    return None if document is None else _version(document)

  def has_stale_version(
    self,
    *,
    tenant_id: str,
    project_id: str | None,
    document_ids: tuple[str, ...],
    scope_fingerprint: str,
  ) -> bool:
    return self._versions.find_one(
      {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "document_ids": list(sorted(document_ids)),
        "scope_fingerprint": {"$ne": scope_fingerprint},
        "status": {"$in": sorted(_COMPLETED_STATUSES)},
      },
      {"graph_version_id": 1},
    ) is not None

  def load(self, version: GraphVersionRecord) -> GraphPublication:
    completed = self.completed_version(
      tenant_id=version.tenant_id,
      graph_version_id=version.graph_version_id,
      scope_fingerprint=version.scope_fingerprint,
    )
    if completed is None:
      raise GraphNotFoundError("graph version not found")
    identity = {
      "tenant_id": version.tenant_id,
      "graph_version_id": version.graph_version_id,
    }
    return GraphPublication(
      entities=tuple(
        PublishedEntity.model_validate(_without_storage(item))
        for item in self._nodes.find(identity)
      ),
      relations=tuple(
        PublishedRelation.model_validate(_without_storage(item))
        for item in self._edges.find(identity)
      ),
      evidence=tuple(
        PublishedEvidence.model_validate(_without_storage(item))
        for item in self._evidence.find(identity)
      ),
      gaps=tuple(
        PublishedGap.model_validate(_without_storage(item))
        for item in self._gaps.find(identity)
      ),
    )

  def _clear_staging(self, tenant_id: str, graph_version_id: str) -> None:
    identity = {
      "tenant_id": tenant_id,
      "graph_version_id": graph_version_id,
    }
    for collection in (
      self._nodes,
      self._edges,
      self._evidence,
      self._gaps,
    ):
      collection.delete_many(identity)


def _version(document: dict[str, Any]) -> GraphVersionRecord:
  return GraphVersionRecord(
    graph_version_id=document["graph_version_id"],
    tenant_id=document["tenant_id"],
    build_id=document["build_id"],
    project_id=document.get("project_id"),
    scope_fingerprint=document["scope_fingerprint"],
    document_ids=tuple(document["document_ids"]),
    graph_schema_version=document["graph_schema_version"],
    extractor_version=document["extractor_version"],
    normalization_version=document["normalization_version"],
    status=document["status"],
    created_at=document["created_at"],
    published_at=document.get("published_at"),
    error_code=document.get("error_code"),
  )


def _without_storage(document: dict[str, Any]) -> dict[str, Any]:
  return {
    key: value for key, value in document.items()
    if key not in {"_id", "tenant_id", "graph_version_id"}
  }
