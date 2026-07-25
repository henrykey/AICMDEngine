"""MongoDB implementation of the durable G29 build repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from .contracts import AuthorizedScopeEnvelope, BuildStatus
from .lifecycle import (
  BuildNotFoundError,
  BuildOutcome,
  BuildRecord,
  _durable_scope,
  _required_fingerprint,
)


class MongoBuildRepository:
  """Atomic build lifecycle stored only in ``basin_kg_builds``."""

  def __init__(self, builds: Collection):
    self._builds = builds

  def ensure_indexes(self) -> None:
    self._builds.create_index(
      [("tenant_id", ASCENDING), ("build_id", ASCENDING)],
      unique=True,
      name="tenant_build_unique",
    )
    self._builds.create_index(
      [("tenant_id", ASCENDING), ("scope_fingerprint", ASCENDING)],
      unique=True,
      partialFilterExpression={"reusable": True},
      name="tenant_scope_reusable_unique",
    )
    self._builds.create_index(
      [
        ("status", ASCENDING),
        ("next_attempt_at", ASCENDING),
        ("lease_expires_at", ASCENDING),
      ],
      name="ready_build_scan",
    )

  def start_or_reuse(
    self,
    scope: AuthorizedScopeEnvelope,
    *,
    now: datetime,
  ) -> BuildRecord:
    fingerprint = _required_fingerprint(scope)
    identity = {
      "tenant_id": scope.tenant_id,
      "scope_fingerprint": fingerprint,
    }
    reusable = self._builds.find_one({**identity, "reusable": True})
    if reusable is not None:
      if reusable["status"] == BuildStatus.PAUSED_AUTH_REQUIRED.value:
        resumed = self._builds.find_one_and_update(
          {
            **identity,
            "build_id": reusable["build_id"],
            "status": BuildStatus.PAUSED_AUTH_REQUIRED.value,
          },
          {
            "$set": {
              "request_id": scope.request_id,
              "requested_by": scope.requested_by,
              "source_scope": _durable_scope(scope),
              "status": BuildStatus.QUEUED.value,
              "phase": "QUEUED",
              "next_attempt_at": now,
              "updated_at": now,
              "error_code": None,
            }
          },
          return_document=ReturnDocument.AFTER,
        )
        if resumed is not None:
          reusable = resumed
      return _record(reusable)

    prior = self._builds.find_one(
      identity,
      sort=[("attempt", -1)],
    )
    build_id = _new_build_id()
    document = {
      "build_id": build_id,
      **identity,
      "request_id": scope.request_id,
      "requested_by": scope.requested_by,
      "project_id": scope.project_id,
      "source_scope": _durable_scope(scope),
      "status": BuildStatus.QUEUED.value,
      "phase": "QUEUED",
      "attempt": 1 if prior is None else int(prior["attempt"]) + 1,
      "prior_build_id": None if prior is None else prior["build_id"],
      "retry_count": 0,
      "completed_unit_ids": (
        [] if prior is None else prior.get("completed_unit_ids", [])
      ),
      "checkpoint_results": (
        {} if prior is None else prior.get("checkpoint_results", {})
      ),
      "cancel_requested": False,
      "lease_owner": None,
      "lease_expires_at": None,
      "lease_reclaims": 0,
      "next_attempt_at": now,
      "created_at": now,
      "updated_at": now,
      "started_at": None,
      "completed_at": None,
      "error_code": None,
      "graph_version_id": None,
      "reusable": True,
    }
    try:
      self._builds.insert_one(document)
      return _record(document)
    except DuplicateKeyError:
      raced = self._builds.find_one({**identity, "reusable": True})
      if raced is None:
        raise
      return _record(raced)

  def get_for_scope(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> BuildRecord:
    document = self._builds.find_one({
      "tenant_id": tenant_id,
      "build_id": build_id,
      "scope_fingerprint": scope_fingerprint,
    })
    if document is None:
      raise BuildNotFoundError("build not found")
    return _record(document)

  def latest_for_scope(
    self,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> BuildRecord | None:
    document = self._builds.find_one(
      {
        "tenant_id": tenant_id,
        "scope_fingerprint": scope_fingerprint,
      },
      sort=[("attempt", -1)],
    )
    return None if document is None else _record(document)

  def list_ready(self, *, now: datetime, limit: int) -> tuple[BuildRecord, ...]:
    documents = self._builds.find({
      "$or": [
        {
          "status": BuildStatus.QUEUED.value,
          "next_attempt_at": {"$lte": now},
        },
        {
          "status": BuildStatus.RUNNING.value,
          "lease_expires_at": {"$lte": now},
        },
      ]
    }).sort([
      ("next_attempt_at", ASCENDING),
      ("created_at", ASCENDING),
    ]).limit(limit)
    return tuple(_record(item) for item in documents)

  def claim(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
  ) -> BuildRecord | None:
    base = {"tenant_id": tenant_id, "build_id": build_id}
    claimed = self._builds.find_one_and_update(
      {
        **base,
        "status": BuildStatus.QUEUED.value,
        "next_attempt_at": {"$lte": now},
      },
      {
        "$set": {
          "status": BuildStatus.RUNNING.value,
          "phase": "BUILDING",
          "lease_owner": worker_id,
          "lease_expires_at": now + lease_duration,
          "updated_at": now,
        },
      },
      return_document=ReturnDocument.AFTER,
    )
    if claimed is not None:
      if claimed.get("started_at") is None:
        claimed = self._builds.find_one_and_update(
          {**base, "lease_owner": worker_id},
          {"$set": {"started_at": now}},
          return_document=ReturnDocument.AFTER,
        )
      return _record(claimed)

    reclaimed = self._builds.find_one_and_update(
      {
        **base,
        "status": BuildStatus.RUNNING.value,
        "lease_expires_at": {"$lte": now},
        "lease_reclaims": {"$lt": 1},
      },
      {
        "$set": {
          "lease_owner": worker_id,
          "lease_expires_at": now + lease_duration,
          "updated_at": now,
        },
        "$inc": {"lease_reclaims": 1},
      },
      return_document=ReturnDocument.AFTER,
    )
    if reclaimed is not None:
      return _record(reclaimed)

    self._builds.update_one(
      {
        **base,
        "status": BuildStatus.RUNNING.value,
        "lease_expires_at": {"$lte": now},
        "lease_reclaims": {"$gte": 1},
      },
      {
        "$set": {
          "status": BuildStatus.FAILED.value,
          "phase": "FAILED",
          "lease_owner": None,
          "lease_expires_at": None,
          "error_code": "STALE_LEASE_EXHAUSTED",
          "completed_at": now,
          "updated_at": now,
          "reusable": False,
        }
      },
    )
    return None

  def heartbeat(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
  ) -> None:
    self._require_modified(
      {"tenant_id": tenant_id, "build_id": build_id},
      worker_id,
      {
        "$set": {
          "lease_expires_at": now + lease_duration,
          "updated_at": now,
        }
      },
      accept_matched=True,
    )

  def checkpoint(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    unit_id: str,
    result: dict[str, Any] | None = None,
    now: datetime,
  ) -> None:
    if not unit_id or not unit_id.strip():
      raise ValueError("unit_id is required")
    update: dict[str, Any] = {
      "$addToSet": {"completed_unit_ids": unit_id},
      "$set": {"updated_at": now},
    }
    if result is not None:
      update["$set"][
        f"checkpoint_results.{_checkpoint_key(unit_id)}"
      ] = {
        "unit_id": unit_id,
        "result": result,
      }
    self._require_modified(
      {"tenant_id": tenant_id, "build_id": build_id},
      worker_id,
      update,
      accept_matched=True,
    )

  def is_cancel_requested(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
  ) -> bool:
    document = self._builds.find_one(
      {
        "tenant_id": tenant_id,
        "build_id": build_id,
        "status": BuildStatus.RUNNING.value,
        "lease_owner": worker_id,
      },
      {"cancel_requested": 1},
    )
    if document is None:
      raise RuntimeError("worker does not own the active build lease")
    return bool(document.get("cancel_requested"))

  def complete(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    outcome: BuildOutcome,
    now: datetime,
  ) -> None:
    base = {
      "tenant_id": tenant_id,
      "build_id": build_id,
      "status": BuildStatus.RUNNING.value,
      "lease_owner": worker_id,
    }
    completed = self._builds.update_one(
      {**base, "cancel_requested": False},
      {
        "$set": {
          "status": outcome.value,
          "phase": outcome.value,
          "lease_owner": None,
          "lease_expires_at": None,
          "completed_at": now,
          "updated_at": now,
        }
      },
    )
    if completed.matched_count:
      return
    cancelled = self._builds.update_one(
      {**base, "cancel_requested": True},
      {
        "$set": {
          "status": BuildStatus.CANCELLED.value,
          "phase": "CANCELLED",
          "lease_owner": None,
          "lease_expires_at": None,
          "completed_at": now,
          "updated_at": now,
          "reusable": False,
        }
      },
    )
    if not cancelled.matched_count:
      raise RuntimeError("worker does not own the active build lease")

  def pause_for_authorization(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
  ) -> None:
    self._finish(
      build_id,
      tenant_id=tenant_id,
      worker_id=worker_id,
      status=BuildStatus.PAUSED_AUTH_REQUIRED,
      error_code="AUTHORIZATION_REQUIRED",
      now=now,
      reusable=True,
    )

  def retry_or_fail(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
    max_retries: int,
    next_attempt_at: datetime,
  ) -> None:
    base = {
      "tenant_id": tenant_id,
      "build_id": build_id,
      "status": BuildStatus.RUNNING.value,
      "lease_owner": worker_id,
    }
    retried = self._builds.update_one(
      {**base, "retry_count": {"$lt": max_retries}},
      {
        "$set": {
          "status": BuildStatus.QUEUED.value,
          "phase": "RETRY_WAIT",
          "lease_owner": None,
          "lease_expires_at": None,
          "next_attempt_at": next_attempt_at,
          "error_code": "TRANSIENT_FAILURE",
          "updated_at": now,
        },
        "$inc": {"retry_count": 1},
      },
    )
    if retried.matched_count:
      return
    self._finish(
      build_id,
      tenant_id=tenant_id,
      worker_id=worker_id,
      status=BuildStatus.FAILED,
      error_code="TRANSIENT_RETRIES_EXHAUSTED",
      now=now,
      reusable=False,
    )

  def fail(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    error_code: str,
    now: datetime,
    error_diagnostic: dict[str, Any] | None = None,
  ) -> None:
    self._finish(
      build_id,
      tenant_id=tenant_id,
      worker_id=worker_id,
      status=BuildStatus.FAILED,
      error_code=error_code,
      now=now,
      reusable=False,
      error_diagnostic=error_diagnostic,
    )

  def request_cancel(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
    now: datetime,
  ) -> None:
    base = {
      "tenant_id": tenant_id,
      "build_id": build_id,
      "scope_fingerprint": scope_fingerprint,
    }
    queued = self._builds.update_one(
      {**base, "status": BuildStatus.QUEUED.value},
      {
        "$set": {
          "status": BuildStatus.CANCELLED.value,
          "phase": "CANCELLED",
          "cancel_requested": True,
          "completed_at": now,
          "updated_at": now,
          "reusable": False,
        }
      },
    )
    if queued.matched_count:
      return
    self._builds.update_one(
      {**base, "status": BuildStatus.RUNNING.value},
      {"$set": {"cancel_requested": True, "updated_at": now}},
    )

  def resume_paused(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
    now: datetime,
  ) -> None:
    self._builds.update_one(
      {
        "tenant_id": tenant_id,
        "build_id": build_id,
        "scope_fingerprint": scope_fingerprint,
        "status": BuildStatus.PAUSED_AUTH_REQUIRED.value,
      },
      {
        "$set": {
          "status": BuildStatus.QUEUED.value,
          "phase": "QUEUED",
          "next_attempt_at": now,
          "completed_at": None,
          "error_code": None,
          "updated_at": now,
        }
      },
    )

  def set_graph_version(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    graph_version_id: str,
    now: datetime,
  ) -> None:
    self._require_modified(
      {"tenant_id": tenant_id, "build_id": build_id},
      worker_id,
      {
        "$set": {
          "graph_version_id": graph_version_id,
          "updated_at": now,
        }
      },
      accept_matched=True,
    )

  def _require_modified(
    self,
    identity: dict[str, Any],
    worker_id: str,
    update: dict[str, Any],
    *,
    accept_matched: bool = False,
  ) -> None:
    result = self._builds.update_one(
      {
        **identity,
        "status": BuildStatus.RUNNING.value,
        "lease_owner": worker_id,
      },
      update,
    )
    succeeded = result.matched_count if accept_matched else result.modified_count
    if not succeeded:
      raise RuntimeError("worker does not own the active build lease")

  def _finish(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    status: BuildStatus,
    error_code: str,
    now: datetime,
    reusable: bool,
    error_diagnostic: dict[str, Any] | None = None,
  ) -> None:
    result = self._builds.update_one(
      {
        "tenant_id": tenant_id,
        "build_id": build_id,
        "status": BuildStatus.RUNNING.value,
        "lease_owner": worker_id,
      },
      {
        "$set": {
          "status": status.value,
          "phase": status.value,
          "lease_owner": None,
          "lease_expires_at": None,
          "error_code": error_code,
          "error_diagnostic": error_diagnostic,
          "completed_at": now,
          "updated_at": now,
          "reusable": reusable,
        }
      },
    )
    if not result.matched_count:
      raise RuntimeError("worker does not own the active build lease")


def _record(document: dict[str, Any]) -> BuildRecord:
  return BuildRecord(
    build_id=document["build_id"],
    tenant_id=document["tenant_id"],
    scope_fingerprint=document["scope_fingerprint"],
    request_id=document["request_id"],
    requested_by=document["requested_by"],
    project_id=document.get("project_id"),
    source_scope=document["source_scope"],
    status=BuildStatus(document["status"]),
    phase=document["phase"],
    attempt=int(document["attempt"]),
    prior_build_id=document.get("prior_build_id"),
    retry_count=int(document.get("retry_count", 0)),
    completed_unit_ids=tuple(document.get("completed_unit_ids", [])),
    cancel_requested=bool(document.get("cancel_requested", False)),
    lease_owner=document.get("lease_owner"),
    lease_expires_at=_aware(document.get("lease_expires_at")),
    lease_reclaims=int(document.get("lease_reclaims", 0)),
    next_attempt_at=_aware(document["next_attempt_at"]),
    created_at=_aware(document["created_at"]),
    updated_at=_aware(document["updated_at"]),
    started_at=_aware(document.get("started_at")),
    completed_at=_aware(document.get("completed_at")),
    error_code=document.get("error_code"),
    error_diagnostic=document.get("error_diagnostic"),
    checkpoint_results={
      value["unit_id"]: value["result"]
      for value in document.get("checkpoint_results", {}).values()
    },
    graph_version_id=document.get("graph_version_id"),
  )


def _aware(value: datetime | None) -> datetime | None:
  if value is None or value.tzinfo is not None:
    return value
  return value.replace(tzinfo=timezone.utc)


def _new_build_id() -> str:
  from uuid import uuid4

  return f"build-{uuid4()}"


def _checkpoint_key(unit_id: str) -> str:
  from hashlib import sha256

  return sha256(unit_id.encode("utf-8")).hexdigest()
