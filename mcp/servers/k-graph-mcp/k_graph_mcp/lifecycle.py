"""Durable asynchronous build lifecycle for the BasinComparator graph."""

from __future__ import annotations

import logging
import random
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Callable, Protocol

from .contracts import AuthorizedScopeEnvelope, BuildStatus


LOGGER = logging.getLogger(__name__)
REUSABLE_STATUSES = {
  BuildStatus.QUEUED,
  BuildStatus.RUNNING,
  BuildStatus.COMPLETED,
  BuildStatus.COMPLETED_WITH_GAPS,
  BuildStatus.PAUSED_AUTH_REQUIRED,
}


class BuildNotFoundError(LookupError):
  """Returned for missing and out-of-scope builds alike."""


class RetryableBuildError(RuntimeError):
  """A bounded transient failure such as timeout, 429, or 5xx."""


class AuthorizationRequiredError(RuntimeError):
  """Internal service authorization must be refreshed before resuming."""


class BuildCancelledError(RuntimeError):
  """The durable cancellation flag was observed between work units."""


class BuildOutcome(StrEnum):
  COMPLETED = "COMPLETED"
  COMPLETED_WITH_GAPS = "COMPLETED_WITH_GAPS"


@dataclass(frozen=True)
class BuildRecord:
  build_id: str
  tenant_id: str
  scope_fingerprint: str
  request_id: str
  requested_by: str
  project_id: str | None
  source_scope: dict[str, Any]
  status: BuildStatus
  phase: str
  attempt: int
  prior_build_id: str | None
  retry_count: int
  completed_unit_ids: tuple[str, ...]
  cancel_requested: bool
  lease_owner: str | None
  lease_expires_at: datetime | None
  lease_reclaims: int
  next_attempt_at: datetime
  created_at: datetime
  updated_at: datetime
  started_at: datetime | None = None
  completed_at: datetime | None = None
  error_code: str | None = None
  checkpoint_results: dict[str, Any] = field(default_factory=dict)
  graph_version_id: str | None = None


class BuildRepository(Protocol):
  def start_or_reuse(
    self,
    scope: AuthorizedScopeEnvelope,
    *,
    now: datetime,
  ) -> BuildRecord: ...

  def get_for_scope(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> BuildRecord: ...

  def latest_for_scope(
    self,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> BuildRecord | None: ...

  def list_ready(self, *, now: datetime, limit: int) -> tuple[BuildRecord, ...]: ...

  def claim(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
  ) -> BuildRecord | None: ...

  def heartbeat(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
  ) -> None: ...

  def checkpoint(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    unit_id: str,
    result: dict[str, Any] | None,
    now: datetime,
  ) -> None: ...

  def is_cancel_requested(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
  ) -> bool: ...

  def complete(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    outcome: BuildOutcome,
    now: datetime,
  ) -> None: ...

  def pause_for_authorization(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
  ) -> None: ...

  def retry_or_fail(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
    max_retries: int,
    next_attempt_at: datetime,
  ) -> None: ...

  def fail(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    error_code: str,
    now: datetime,
  ) -> None: ...

  def request_cancel(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
    now: datetime,
  ) -> None: ...

  def resume_paused(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
    now: datetime,
  ) -> None: ...

  def set_graph_version(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    graph_version_id: str,
    now: datetime,
  ) -> None: ...


class BuildRunner(Protocol):
  def run(self, context: "BuildContext") -> BuildOutcome: ...


class BuildMetrics(Protocol):
  def record_terminal(
    self,
    *,
    status: BuildStatus,
    duration_ms: int,
    completed_units: int,
    retry_count: int,
  ) -> None: ...


class NoopBuildMetrics:
  def record_terminal(
    self,
    *,
    status: BuildStatus,
    duration_ms: int,
    completed_units: int,
    retry_count: int,
  ) -> None:
    return None


class VolatileServiceTokenRegistry:
  """Process-memory service JWTs; tokens are deliberately never persisted."""

  def __init__(self):
    self._tokens: dict[str, str] = {}
    self._lock = threading.Lock()

  def put(self, tenant_id: str, token: str) -> None:
    if not token or not token.strip():
      raise ValueError("service token is required")
    with self._lock:
      self._tokens[tenant_id] = token

  def get_token(self, tenant_id: str) -> str:
    with self._lock:
      token = self._tokens.get(tenant_id)
    if token is None:
      raise AuthorizationRequiredError(
        "fresh Membership service authorization is required"
      )
    return token


class InMemoryBuildRepository:
  """Thread-safe reference semantics used by focused lifecycle tests."""

  def __init__(self):
    self._records: dict[str, BuildRecord] = {}
    self._lock = threading.RLock()

  def start_or_reuse(
    self,
    scope: AuthorizedScopeEnvelope,
    *,
    now: datetime,
  ) -> BuildRecord:
    fingerprint = _required_fingerprint(scope)
    with self._lock:
      compatible = [
        item for item in self._records.values()
        if item.tenant_id == scope.tenant_id
        and item.scope_fingerprint == fingerprint
      ]
      reusable = next(
        (item for item in compatible if item.status in REUSABLE_STATUSES),
        None,
      )
      if reusable is not None:
        if reusable.status == BuildStatus.PAUSED_AUTH_REQUIRED:
          reusable = replace(
            reusable,
            request_id=scope.request_id,
            requested_by=scope.requested_by,
            status=BuildStatus.QUEUED,
            phase="QUEUED",
            next_attempt_at=now,
            updated_at=now,
            error_code=None,
          )
          self._records[reusable.build_id] = reusable
        return reusable

      prior = max(compatible, key=lambda item: item.attempt, default=None)
      record = BuildRecord(
        build_id=f"build-{uuid.uuid4()}",
        tenant_id=scope.tenant_id,
        scope_fingerprint=fingerprint,
        request_id=scope.request_id,
        requested_by=scope.requested_by,
        project_id=scope.project_id,
        source_scope=_durable_scope(scope),
        status=BuildStatus.QUEUED,
        phase="QUEUED",
        attempt=1 if prior is None else prior.attempt + 1,
        prior_build_id=None if prior is None else prior.build_id,
        retry_count=0,
        completed_unit_ids=(
          () if prior is None else prior.completed_unit_ids
        ),
        checkpoint_results=(
          {} if prior is None else dict(prior.checkpoint_results)
        ),
        cancel_requested=False,
        lease_owner=None,
        lease_expires_at=None,
        lease_reclaims=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
      )
      self._records[record.build_id] = record
      return record

  def get_for_scope(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> BuildRecord:
    with self._lock:
      record = self._records.get(build_id)
      if (
        record is None
        or record.tenant_id != tenant_id
        or record.scope_fingerprint != scope_fingerprint
      ):
        raise BuildNotFoundError("build not found")
      return record

  def latest_for_scope(
    self,
    *,
    tenant_id: str,
    scope_fingerprint: str,
  ) -> BuildRecord | None:
    with self._lock:
      matches = [
        item for item in self._records.values()
        if item.tenant_id == tenant_id
        and item.scope_fingerprint == scope_fingerprint
      ]
      return max(matches, key=lambda item: item.attempt, default=None)

  def list_ready(self, *, now: datetime, limit: int) -> tuple[BuildRecord, ...]:
    with self._lock:
      ready = [
        item for item in self._records.values()
        if (
          item.status == BuildStatus.QUEUED
          and item.next_attempt_at <= now
        ) or (
          item.status == BuildStatus.RUNNING
          and item.lease_expires_at is not None
          and item.lease_expires_at <= now
        )
      ]
      ready.sort(key=lambda item: (item.next_attempt_at, item.created_at))
      return tuple(ready[:limit])

  def claim(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
  ) -> BuildRecord | None:
    with self._lock:
      record = self._records.get(build_id)
      if record is None or record.tenant_id != tenant_id:
        return None
      if record.status == BuildStatus.RUNNING:
        if record.lease_expires_at is None or record.lease_expires_at > now:
          return None
        if record.lease_reclaims >= 1:
          self._records[build_id] = replace(
            record,
            status=BuildStatus.FAILED,
            phase="FAILED",
            lease_owner=None,
            lease_expires_at=None,
            error_code="STALE_LEASE_EXHAUSTED",
            completed_at=now,
            updated_at=now,
          )
          return None
        record = replace(record, lease_reclaims=record.lease_reclaims + 1)
      elif (
        record.status != BuildStatus.QUEUED
        or record.next_attempt_at > now
      ):
        return None
      claimed = replace(
        record,
        status=BuildStatus.RUNNING,
        phase="BUILDING",
        lease_owner=worker_id,
        lease_expires_at=now + lease_duration,
        started_at=record.started_at or now,
        updated_at=now,
      )
      self._records[build_id] = claimed
      return claimed

  def heartbeat(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    now: datetime,
    lease_duration: timedelta,
  ) -> None:
    with self._lock:
      record = self._owned_running(build_id, tenant_id, worker_id)
      self._records[build_id] = replace(
        record,
        lease_expires_at=now + lease_duration,
        updated_at=now,
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
    with self._lock:
      record = self._owned_running(build_id, tenant_id, worker_id)
      self._records[build_id] = replace(
        record,
        graph_version_id=graph_version_id,
        updated_at=now,
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
    with self._lock:
      record = self._owned_running(build_id, tenant_id, worker_id)
      units = record.completed_unit_ids
      if unit_id not in units:
        units = (*units, unit_id)
      self._records[build_id] = replace(
        record,
        completed_unit_ids=units,
        checkpoint_results={
          **record.checkpoint_results,
          **({unit_id: result} if result is not None else {}),
        },
        updated_at=now,
      )

  def is_cancel_requested(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
  ) -> bool:
    with self._lock:
      return self._owned_running(
        build_id,
        tenant_id,
        worker_id,
      ).cancel_requested

  def complete(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    outcome: BuildOutcome,
    now: datetime,
  ) -> None:
    status = BuildStatus(outcome.value)
    with self._lock:
      record = self._owned_running(build_id, tenant_id, worker_id)
      if record.cancel_requested:
        status = BuildStatus.CANCELLED
      self._records[build_id] = replace(
        record,
        status=status,
        phase=status.value,
        lease_owner=None,
        lease_expires_at=None,
        completed_at=now,
        updated_at=now,
      )

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
    with self._lock:
      record = self._owned_running(build_id, tenant_id, worker_id)
      retry_count = record.retry_count + 1
      if retry_count > max_retries:
        self._records[build_id] = replace(
          record,
          status=BuildStatus.FAILED,
          phase="FAILED",
          retry_count=record.retry_count,
          lease_owner=None,
          lease_expires_at=None,
          error_code="TRANSIENT_RETRIES_EXHAUSTED",
          completed_at=now,
          updated_at=now,
        )
        return
      self._records[build_id] = replace(
        record,
        status=BuildStatus.QUEUED,
        phase="RETRY_WAIT",
        retry_count=retry_count,
        lease_owner=None,
        lease_expires_at=None,
        next_attempt_at=next_attempt_at,
        error_code="TRANSIENT_FAILURE",
        updated_at=now,
      )

  def fail(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    error_code: str,
    now: datetime,
  ) -> None:
    self._finish(
      build_id,
      tenant_id=tenant_id,
      worker_id=worker_id,
      status=BuildStatus.FAILED,
      error_code=error_code,
      now=now,
    )

  def request_cancel(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
    now: datetime,
  ) -> None:
    with self._lock:
      record = self.get_for_scope(
        build_id,
        tenant_id=tenant_id,
        scope_fingerprint=scope_fingerprint,
      )
      if record.status == BuildStatus.QUEUED:
        self._records[build_id] = replace(
          record,
          status=BuildStatus.CANCELLED,
          phase="CANCELLED",
          cancel_requested=True,
          completed_at=now,
          updated_at=now,
        )
      elif record.status == BuildStatus.RUNNING:
        self._records[build_id] = replace(
          record,
          cancel_requested=True,
          updated_at=now,
        )

  def resume_paused(
    self,
    build_id: str,
    *,
    tenant_id: str,
    scope_fingerprint: str,
    now: datetime,
  ) -> None:
    with self._lock:
      record = self.get_for_scope(
        build_id,
        tenant_id=tenant_id,
        scope_fingerprint=scope_fingerprint,
      )
      if record.status == BuildStatus.PAUSED_AUTH_REQUIRED:
        self._records[build_id] = replace(
          record,
          status=BuildStatus.QUEUED,
          phase="QUEUED",
          next_attempt_at=now,
          completed_at=None,
          error_code=None,
          updated_at=now,
        )

  def _owned_running(
    self,
    build_id: str,
    tenant_id: str,
    worker_id: str,
  ) -> BuildRecord:
    record = self._records.get(build_id)
    if (
      record is None
      or record.tenant_id != tenant_id
      or record.status != BuildStatus.RUNNING
      or record.lease_owner != worker_id
    ):
      raise RuntimeError("worker does not own the active build lease")
    return record

  def _finish(
    self,
    build_id: str,
    *,
    tenant_id: str,
    worker_id: str,
    status: BuildStatus,
    error_code: str,
    now: datetime,
  ) -> None:
    with self._lock:
      record = self._owned_running(build_id, tenant_id, worker_id)
      self._records[build_id] = replace(
        record,
        status=status,
        phase=status.value,
        lease_owner=None,
        lease_expires_at=None,
        error_code=error_code,
        completed_at=now,
        updated_at=now,
      )


class BuildContext:
  def __init__(
    self,
    *,
    record: BuildRecord,
    repository: BuildRepository,
    worker_id: str,
    lease_duration: timedelta,
    clock: Callable[[], datetime],
  ):
    self.record = record
    self._repository = repository
    self._worker_id = worker_id
    self._lease_duration = lease_duration
    self._clock = clock

  @property
  def completed_unit_ids(self) -> tuple[str, ...]:
    current = self._repository.get_for_scope(
      self.record.build_id,
      tenant_id=self.record.tenant_id,
      scope_fingerprint=self.record.scope_fingerprint,
    )
    return current.completed_unit_ids

  def checkpoint(
    self,
    unit_id: str,
    result: dict[str, Any] | None = None,
  ) -> None:
    now = self._clock()
    self._repository.checkpoint(
      self.record.build_id,
      tenant_id=self.record.tenant_id,
      worker_id=self._worker_id,
      unit_id=unit_id,
      result=result,
      now=now,
    )
    self._repository.heartbeat(
      self.record.build_id,
      tenant_id=self.record.tenant_id,
      worker_id=self._worker_id,
      now=now,
      lease_duration=self._lease_duration,
    )

  def raise_if_cancelled(self) -> None:
    if self._repository.is_cancel_requested(
      self.record.build_id,
      tenant_id=self.record.tenant_id,
      worker_id=self._worker_id,
    ):
      raise BuildCancelledError("build cancellation requested")

  def checkpoint_result(self, unit_id: str) -> dict[str, Any] | None:
    current = self._repository.get_for_scope(
      self.record.build_id,
      tenant_id=self.record.tenant_id,
      scope_fingerprint=self.record.scope_fingerprint,
    )
    return current.checkpoint_results.get(unit_id)

  def current_record(self) -> BuildRecord:
    return self._repository.get_for_scope(
      self.record.build_id,
      tenant_id=self.record.tenant_id,
      scope_fingerprint=self.record.scope_fingerprint,
    )

  def set_graph_version(self, graph_version_id: str) -> None:
    self._repository.set_graph_version(
      self.record.build_id,
      tenant_id=self.record.tenant_id,
      worker_id=self._worker_id,
      graph_version_id=graph_version_id,
      now=self._clock(),
    )


class BuildCoordinator:
  """Bounded dispatcher; request threads only persist work and signal it."""

  def __init__(
    self,
    *,
    repository: BuildRepository,
    runner: BuildRunner,
    max_workers: int = 2,
    max_retries: int = 2,
    lease_duration: timedelta = timedelta(minutes=2),
    retry_delay: Callable[[int], float] | None = None,
    poll_interval_seconds: float = 1,
    clock: Callable[[], datetime] | None = None,
    metrics: BuildMetrics | None = None,
    credential_registry: VolatileServiceTokenRegistry | None = None,
    graph_query: Any | None = None,
    autostart: bool = True,
  ):
    if max_workers < 1:
      raise ValueError("max_workers must be at least 1")
    self._repository = repository
    self._runner = runner
    self._max_workers = max_workers
    self._max_retries = max_retries
    self._lease_duration = lease_duration
    self._retry_delay = retry_delay or _default_retry_delay
    self._poll_interval_seconds = poll_interval_seconds
    self._clock = clock or (lambda: datetime.now(timezone.utc))
    self._metrics = metrics or NoopBuildMetrics()
    self._credential_registry = credential_registry
    self._graph_query = graph_query
    self._executor = ThreadPoolExecutor(
      max_workers=max_workers,
      thread_name_prefix="k-graph-build",
    )
    self._active: set[str] = set()
    self._lock = threading.Lock()
    self._wake = threading.Event()
    self._closed = threading.Event()
    self._dispatcher: threading.Thread | None = None
    if autostart:
      self._dispatcher = threading.Thread(
        target=self._dispatch_loop,
        name="k-graph-dispatcher",
        daemon=True,
      )
      self._dispatcher.start()

  def start(
    self,
    scope: AuthorizedScopeEnvelope,
    service_token: str | None = None,
  ) -> dict[str, Any]:
    self._refresh_service_token(scope.tenant_id, service_token)
    record = self._repository.start_or_reuse(scope, now=self._clock())
    self._wake.set()
    return build_status_payload(record)

  def status(
    self,
    build_id: str,
    scope: AuthorizedScopeEnvelope,
    service_token: str | None = None,
  ) -> dict[str, Any]:
    self._refresh_service_token(scope.tenant_id, service_token)
    if service_token is not None and self._credential_registry is not None:
      self._repository.resume_paused(
        build_id,
        tenant_id=scope.tenant_id,
        scope_fingerprint=_required_fingerprint(scope),
        now=self._clock(),
      )
    record = self._repository.get_for_scope(
      build_id,
      tenant_id=scope.tenant_id,
      scope_fingerprint=_required_fingerprint(scope),
    )
    return build_status_payload(record)

  def query(
    self,
    scope: AuthorizedScopeEnvelope,
    *,
    graph_version_id: str | None,
    basin: str | None,
    target: str | None,
  ) -> dict[str, Any]:
    if self._graph_query is None:
      raise RuntimeError("G29.4 graph query backend is not configured")
    return self._graph_query.query(
      scope,
      graph_version_id=graph_version_id,
      basin=basin,
      target=target,
    )

  def dispatch_once(self) -> int:
    with self._lock:
      capacity = self._max_workers - len(self._active)
    if capacity <= 0:
      return 0
    records = self._repository.list_ready(now=self._clock(), limit=capacity)
    submitted = 0
    for record in records:
      with self._lock:
        if record.build_id in self._active:
          continue
        self._active.add(record.build_id)
      self._executor.submit(
        self._run_build,
        record.build_id,
        record.tenant_id,
      )
      submitted += 1
    return submitted

  def close(self) -> None:
    self._closed.set()
    self._wake.set()
    if self._dispatcher is not None:
      self._dispatcher.join(timeout=2)
    self._executor.shutdown(wait=True)

  def _dispatch_loop(self) -> None:
    while not self._closed.is_set():
      self.dispatch_once()
      self._wake.wait(self._poll_interval_seconds)
      self._wake.clear()

  def _run_build(self, build_id: str, tenant_id: str) -> None:
    worker_id = f"{threading.current_thread().name}:{uuid.uuid4()}"
    started = self._clock()
    claimed = self._repository.claim(
      build_id,
      tenant_id=tenant_id,
      worker_id=worker_id,
      now=started,
      lease_duration=self._lease_duration,
    )
    if claimed is None:
      self._finish_active(build_id)
      return
    LOGGER.info(
      "basin graph build started",
      extra=_log_fields(claimed, worker_id=worker_id),
    )
    context = BuildContext(
      record=claimed,
      repository=self._repository,
      worker_id=worker_id,
      lease_duration=self._lease_duration,
      clock=self._clock,
    )
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
      target=self._heartbeat_loop,
      args=(claimed, worker_id, heartbeat_stop),
      name=f"k-graph-heartbeat-{build_id}",
      daemon=True,
    )
    heartbeat.start()
    try:
      context.raise_if_cancelled()
      outcome = self._runner.run(context)
      if context.current_record().graph_version_id is None:
        context.raise_if_cancelled()
      self._repository.complete(
        build_id,
        tenant_id=claimed.tenant_id,
        worker_id=worker_id,
        outcome=outcome,
        now=self._clock(),
      )
    except BuildCancelledError:
      self._repository.complete(
        build_id,
        tenant_id=claimed.tenant_id,
        worker_id=worker_id,
        outcome=BuildOutcome.COMPLETED,
        now=self._clock(),
      )
    except AuthorizationRequiredError:
      self._repository.pause_for_authorization(
        build_id,
        tenant_id=claimed.tenant_id,
        worker_id=worker_id,
        now=self._clock(),
      )
    except RetryableBuildError:
      current = self._repository.get_for_scope(
        build_id,
        tenant_id=claimed.tenant_id,
        scope_fingerprint=claimed.scope_fingerprint,
      )
      retry_number = current.retry_count + 1
      next_attempt_at = self._clock() + timedelta(
        seconds=self._retry_delay(retry_number)
      )
      self._repository.retry_or_fail(
        build_id,
        tenant_id=claimed.tenant_id,
        worker_id=worker_id,
        now=self._clock(),
        max_retries=self._max_retries,
        next_attempt_at=next_attempt_at,
      )
    except Exception:
      LOGGER.exception(
        "basin graph build failed",
        extra=_log_fields(claimed, worker_id=worker_id),
      )
      self._repository.fail(
        build_id,
        tenant_id=claimed.tenant_id,
        worker_id=worker_id,
        error_code="NON_RETRYABLE_FAILURE",
        now=self._clock(),
      )
    finally:
      heartbeat_stop.set()
      heartbeat.join(timeout=1)
      self._finish_active(build_id)
      terminal = self._repository.get_for_scope(
        build_id,
        tenant_id=claimed.tenant_id,
        scope_fingerprint=claimed.scope_fingerprint,
      )
      LOGGER.info(
        "basin graph build attempt ended",
        extra={
          **_log_fields(terminal, worker_id=worker_id),
          "duration_ms": int(
            (self._clock() - started).total_seconds() * 1000
          ),
        },
      )
      self._metrics.record_terminal(
        status=terminal.status,
        duration_ms=int(
          (self._clock() - started).total_seconds() * 1000
        ),
        completed_units=len(terminal.completed_unit_ids),
        retry_count=terminal.retry_count,
      )

  def _finish_active(self, build_id: str) -> None:
    with self._lock:
      self._active.discard(build_id)
    self._wake.set()

  def _refresh_service_token(
    self,
    tenant_id: str,
    service_token: str | None,
  ) -> None:
    if self._credential_registry is None:
      return
    if service_token is None:
      raise ValueError("service_token is required")
    self._credential_registry.put(tenant_id, service_token)

  def _heartbeat_loop(
    self,
    record: BuildRecord,
    worker_id: str,
    stop: threading.Event,
  ) -> None:
    interval = max(0.05, self._lease_duration.total_seconds() / 3)
    while not stop.wait(interval):
      try:
        self._repository.heartbeat(
          record.build_id,
          tenant_id=record.tenant_id,
          worker_id=worker_id,
          now=self._clock(),
          lease_duration=self._lease_duration,
        )
      except RuntimeError:
        return


def build_status_payload(record: BuildRecord) -> dict[str, Any]:
  return {
    "build_id": record.build_id,
    "status": record.status.value,
    "phase": record.phase,
    "attempt": record.attempt,
    "prior_build_id": record.prior_build_id,
    "retry_count": record.retry_count,
    "completed_units": len(record.completed_unit_ids),
    "error_code": record.error_code,
    "graph_version_id": record.graph_version_id,
    "created_at": record.created_at.isoformat(),
    "updated_at": record.updated_at.isoformat(),
  }


def _required_fingerprint(scope: AuthorizedScopeEnvelope) -> str:
  if scope.scope_fingerprint is None:
    raise ValueError("scope_fingerprint is required")
  return scope.scope_fingerprint


def _durable_scope(scope: AuthorizedScopeEnvelope) -> dict[str, Any]:
  return {
    "tenant_id": scope.tenant_id,
    "project_id": scope.project_id,
    "document_group": [
      item.model_dump(mode="json") for item in scope.document_group
    ],
    "graph_schema_version": scope.graph_schema_version,
    "extractor_version": scope.extractor_version,
    "normalization_version": scope.normalization_version,
  }


def _default_retry_delay(retry_count: int) -> float:
  capped = min(60, 2 ** max(0, retry_count - 1))
  return capped + random.uniform(0, min(1, capped / 4))


def _log_fields(
  record: BuildRecord,
  *,
  worker_id: str,
) -> dict[str, Any]:
  return {
    "build_id": record.build_id,
    "tenant_id": record.tenant_id,
    "phase": record.phase,
    "attempt": record.attempt,
    "retry_count": record.retry_count,
    "completed_units": len(record.completed_unit_ids),
    "worker_id": worker_id,
  }
