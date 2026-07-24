import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from k_graph_mcp.contracts import (
  AuthorizedScopeEnvelope,
  BuildStatus,
  DocumentScopeItem,
  canonical_scope_fingerprint,
)
from k_graph_mcp.lifecycle import (
  AuthorizationRequiredError,
  BuildCoordinator,
  BuildNotFoundError,
  BuildOutcome,
  InMemoryBuildRepository,
  RetryableBuildError,
  VolatileServiceTokenRegistry,
)


HASH_A = "sha256:" + "a" * 64


def test_start_returns_promptly_and_duplicate_start_reuses_build() -> None:
  release = threading.Event()
  runner = BlockingRunner(release)
  repository = InMemoryBuildRepository()
  coordinator = BuildCoordinator(
    repository=repository,
    runner=runner,
    max_workers=1,
    poll_interval_seconds=0.01,
  )
  try:
    started_at = time.monotonic()
    first = coordinator.start(scope())
    elapsed = time.monotonic() - started_at
    second = coordinator.start(scope(request_id="request-2"))

    assert elapsed < 0.2
    assert first["build_id"] == second["build_id"]
    assert runner.started.wait(timeout=1)
    assert coordinator.status(first["build_id"], scope())["status"] == "RUNNING"
  finally:
    release.set()
    coordinator.close()


def test_atomic_lease_prevents_two_workers_from_claiming_same_build() -> None:
  repository = InMemoryBuildRepository()
  build = repository.start_or_reuse(scope(), now=utc(10))

  first = repository.claim(
    build.build_id,
    tenant_id="12",
    worker_id="worker-a",
    now=utc(11),
    lease_duration=timedelta(seconds=30),
  )
  second = repository.claim(
    build.build_id,
    tenant_id="12",
    worker_id="worker-b",
    now=utc(12),
    lease_duration=timedelta(seconds=30),
  )

  assert first is not None
  assert second is None


def test_stale_lease_is_reclaimed_once_and_checkpoint_survives_restart() -> None:
  repository = InMemoryBuildRepository()
  build = repository.start_or_reuse(scope(), now=utc(10))
  assert repository.claim(
    build.build_id,
    tenant_id="12",
    worker_id="worker-a",
    now=utc(11),
    lease_duration=timedelta(seconds=5),
  )
  repository.checkpoint(
    build.build_id,
    tenant_id="12",
    worker_id="worker-a",
    unit_id="doc-1/page-1",
    result={"relations": [{"relation_type": "HAS_PART"}]},
    now=utc(12),
  )

  reclaimed = repository.claim(
    build.build_id,
    tenant_id="12",
    worker_id="worker-b",
    now=utc(17),
    lease_duration=timedelta(seconds=5),
  )
  refused = repository.claim(
    build.build_id,
    tenant_id="12",
    worker_id="worker-c",
    now=utc(23),
    lease_duration=timedelta(seconds=5),
  )

  assert reclaimed is not None
  assert reclaimed.lease_reclaims == 1
  assert reclaimed.completed_unit_ids == ("doc-1/page-1",)
  assert reclaimed.checkpoint_results == {
    "doc-1/page-1": {"relations": [{"relation_type": "HAS_PART"}]}
  }
  assert refused is None
  assert repository.get_for_scope(
    build.build_id,
    tenant_id="12",
    scope_fingerprint=build.scope_fingerprint,
  ).status == BuildStatus.FAILED


@pytest.mark.parametrize(
  ("error", "expected_status"),
  [
    (AuthorizationRequiredError("service authorization expired"), "PAUSED_AUTH_REQUIRED"),
    (RuntimeError("invalid structured output"), "FAILED"),
  ],
)
def test_terminal_failure_boundaries(error, expected_status) -> None:
  repository = InMemoryBuildRepository()
  coordinator = BuildCoordinator(
    repository=repository,
    runner=RaisingRunner(error),
    max_workers=1,
    poll_interval_seconds=0.01,
  )
  try:
    build = coordinator.start(scope())
    status = wait_for_status(coordinator, build["build_id"], expected_status)
    assert status["status"] == expected_status
  finally:
    coordinator.close()


def test_retry_is_bounded_and_duplicate_after_failure_creates_new_attempt() -> None:
  repository = InMemoryBuildRepository()
  coordinator = BuildCoordinator(
    repository=repository,
    runner=RaisingRunner(RetryableBuildError("timeout")),
    max_workers=1,
    max_retries=1,
    retry_delay=lambda retry_count: 0,
    poll_interval_seconds=0.01,
  )
  try:
    first = coordinator.start(scope())
    failed = wait_for_status(coordinator, first["build_id"], "FAILED")
    second = coordinator.start(scope(request_id="request-2"))

    assert failed["retry_count"] == 1
    assert second["build_id"] != first["build_id"]
    assert second["attempt"] == 2
    assert second["prior_build_id"] == first["build_id"]
  finally:
    coordinator.close()


def test_cancel_request_is_observed_between_units() -> None:
  repository = InMemoryBuildRepository()
  first_unit_done = threading.Event()
  continue_runner = threading.Event()
  coordinator = BuildCoordinator(
    repository=repository,
    runner=TwoUnitRunner(first_unit_done, continue_runner),
    max_workers=1,
    poll_interval_seconds=0.01,
  )
  try:
    build = coordinator.start(scope())
    assert first_unit_done.wait(timeout=1)
    repository.request_cancel(
      build["build_id"],
      tenant_id="12",
      scope_fingerprint=scope().scope_fingerprint,
      now=datetime.now(timezone.utc),
    )
    continue_runner.set()

    status = wait_for_status(coordinator, build["build_id"], "CANCELLED")
    assert status["completed_units"] == 1
  finally:
    continue_runner.set()
    coordinator.close()


def test_status_scope_mismatch_is_indistinguishable_from_missing_build() -> None:
  repository = InMemoryBuildRepository()
  coordinator = BuildCoordinator(
    repository=repository,
    runner=RaisingRunner(RuntimeError("unused")),
    autostart=False,
  )
  build = coordinator.start(scope())

  with pytest.raises(BuildNotFoundError):
    coordinator.status(build["build_id"], scope(tenant_id="99"))


def test_worker_heartbeats_long_unit_and_records_bounded_metrics() -> None:
  repository = InMemoryBuildRepository()
  metrics = RecordingMetrics()
  runner = HeartbeatObservingRunner(repository)
  coordinator = BuildCoordinator(
    repository=repository,
    runner=runner,
    max_workers=1,
    lease_duration=timedelta(milliseconds=60),
    poll_interval_seconds=0.01,
    metrics=metrics,
  )
  try:
    build = coordinator.start(scope())
    wait_for_status(coordinator, build["build_id"], "COMPLETED")
    deadline = time.monotonic() + 1
    while not metrics.records and time.monotonic() < deadline:
      time.sleep(0.01)

    assert runner.heartbeat_observed
    assert metrics.records[0]["status"] == BuildStatus.COMPLETED
    assert set(metrics.records[0]) == {
      "status",
      "duration_ms",
      "completed_units",
      "retry_count",
    }
  finally:
    coordinator.close()


def test_fresh_status_authorization_resumes_paused_build_without_persisting_token() -> None:
  repository = InMemoryBuildRepository()
  registry = VolatileServiceTokenRegistry()
  runner = FirstAuthorizationFailureRunner()
  coordinator = BuildCoordinator(
    repository=repository,
    runner=runner,
    credential_registry=registry,
    max_workers=1,
    poll_interval_seconds=0.01,
  )
  try:
    build = coordinator.start(scope(), "service-token-1")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
      paused = repository.get_for_scope(
        build["build_id"],
        tenant_id="12",
        scope_fingerprint=scope().scope_fingerprint,
      )
      if paused.status == BuildStatus.PAUSED_AUTH_REQUIRED:
        break
      time.sleep(0.01)
    else:
      pytest.fail("build did not pause for fresh authorization")

    coordinator.status(build["build_id"], scope(), "service-token-2")
    completed = wait_for_status(
      coordinator,
      build["build_id"],
      "COMPLETED",
      service_token="service-token-2",
    )
    stored = repository.get_for_scope(
      build["build_id"],
      tenant_id="12",
      scope_fingerprint=scope().scope_fingerprint,
    )

    assert completed["status"] == "COMPLETED"
    assert registry.get_token("12") == "service-token-2"
    assert "service_token" not in stored.source_scope
  finally:
    coordinator.close()


class BlockingRunner:
  def __init__(self, release: threading.Event):
    self.release = release
    self.started = threading.Event()

  def run(self, context):
    self.started.set()
    self.release.wait(timeout=2)
    return BuildOutcome.COMPLETED


class RaisingRunner:
  def __init__(self, error: Exception):
    self.error = error

  def run(self, context):
    raise self.error


class TwoUnitRunner:
  def __init__(self, first_unit_done: threading.Event, continue_runner: threading.Event):
    self.first_unit_done = first_unit_done
    self.continue_runner = continue_runner

  def run(self, context):
    context.checkpoint("doc-1/page-1")
    self.first_unit_done.set()
    self.continue_runner.wait(timeout=2)
    context.raise_if_cancelled()
    context.checkpoint("doc-1/page-2")
    return BuildOutcome.COMPLETED


class HeartbeatObservingRunner:
  def __init__(self, repository: InMemoryBuildRepository):
    self.repository = repository
    self.heartbeat_observed = False

  def run(self, context):
    original_expiry = context.record.lease_expires_at
    time.sleep(0.08)
    current = self.repository.get_for_scope(
      context.record.build_id,
      tenant_id=context.record.tenant_id,
      scope_fingerprint=context.record.scope_fingerprint,
    )
    self.heartbeat_observed = current.lease_expires_at > original_expiry
    return BuildOutcome.COMPLETED


class RecordingMetrics:
  def __init__(self):
    self.records: list[dict] = []

  def record_terminal(self, **values):
    self.records.append(values)


class FirstAuthorizationFailureRunner:
  def __init__(self):
    self.calls = 0

  def run(self, context):
    self.calls += 1
    if self.calls == 1:
      raise AuthorizationRequiredError("refresh required")
    return BuildOutcome.COMPLETED


def wait_for_status(
  coordinator: BuildCoordinator,
  build_id: str,
  expected: str,
  service_token: str | None = None,
) -> dict:
  deadline = time.monotonic() + 2
  while time.monotonic() < deadline:
    status = coordinator.status(build_id, scope(), service_token)
    if status["status"] == expected:
      return status
    time.sleep(0.01)
  pytest.fail(f"build {build_id} did not reach {expected}")


def scope(
  *,
  request_id: str = "request-1",
  tenant_id: str = "12",
) -> AuthorizedScopeEnvelope:
  unsigned = AuthorizedScopeEnvelope(
    request_id=request_id,
    tenant_id=tenant_id,
    requested_by="42",
    project_id="project-1",
    document_group=(
      DocumentScopeItem(document_id="doc-1", version=3, content_hash=HASH_A),
    ),
  )
  return unsigned.model_copy(update={
    "scope_fingerprint": canonical_scope_fingerprint(unsigned),
  })


def utc(second: int) -> datetime:
  return datetime(2026, 7, 24, 0, 0, second, tzinfo=timezone.utc)
