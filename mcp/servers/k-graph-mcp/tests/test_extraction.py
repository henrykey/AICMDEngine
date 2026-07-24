from datetime import datetime, timezone

import pytest

from k_graph_mcp.contracts import BuildStatus
from k_graph_mcp.docintel import ScopedChunk, ScopedPage
from k_graph_mcp.extraction import (
  ExtractionValidationError,
  PageFactExtractor,
  ScopedExtractionRunner,
)
from k_graph_mcp.graph_store import GraphPublisher, InMemoryGraphStore
from k_graph_mcp.lifecycle import (
  BuildContext,
  BuildOutcome,
  InMemoryBuildRepository,
)


HASH_A = "sha256:" + "a" * 64


def test_extracts_only_supported_directed_relation_with_evidence() -> None:
  client = SequenceExtractionClient([valid_extraction()])
  extractor = PageFactExtractor(client=client)

  result = extractor.extract(page())

  assert len(result.entities) == 2
  assert len(result.relations) == 1
  assert result.relations[0].relation_type == "HAS_PART"
  assert result.relations[0].source_entity_type == "BASIN"
  assert result.relations[0].target_entity_type == "DEPRESSION"
  assert result.evidence[0].document_id == "doc-1"
  assert result.evidence[0].page_no == 1
  assert result.evidence[0].chunk_id == "chunk-1"
  assert "page:1/chunk:chunk-1" in result.evidence[0].source_locator


def test_invalid_structured_result_gets_exactly_one_repair_attempt() -> None:
  invalid = valid_extraction()
  invalid["relations"][0]["evidence_quote"] = "红河盆地"
  client = SequenceExtractionClient([invalid, valid_extraction()])
  extractor = PageFactExtractor(client=client)

  result = extractor.extract(page())

  assert len(result.relations) == 1
  assert client.repair_flags == [False, True]


def test_repeated_invalid_result_is_non_retryable_validation_failure() -> None:
  invalid = valid_extraction()
  invalid["entities"][0]["original_mention"] = "不存在的盆地"
  client = SequenceExtractionClient([invalid, invalid])

  with pytest.raises(ExtractionValidationError):
    PageFactExtractor(client=client).extract(page())

  assert client.repair_flags == [False, True]


def test_runner_checkpoints_validated_result_and_reuses_it_after_restart() -> None:
  repository = InMemoryBuildRepository()
  record = repository.start_or_reuse(scope(), now=now())
  claimed = repository.claim(
    record.build_id,
    tenant_id="12",
    worker_id="worker-1",
    now=now(),
    lease_duration=__import__("datetime").timedelta(minutes=1),
  )
  context = BuildContext(
    record=claimed,
    repository=repository,
    worker_id="worker-1",
    lease_duration=__import__("datetime").timedelta(minutes=1),
    clock=now,
  )
  client = SequenceExtractionClient([valid_extraction()])
  runner = ScopedExtractionRunner(
    provider=FakeDocIntelProvider([page()]),
    extractor=PageFactExtractor(client=client),
  )

  first = runner.run(context)
  second = runner.run(context)

  assert first == BuildOutcome.COMPLETED
  assert second == BuildOutcome.COMPLETED
  assert len(client.repair_flags) == 1
  saved = context.checkpoint_result("doc-1/v3/p1/chunk-1/s0")
  assert saved["relations"][0]["relation_type"] == "HAS_PART"


def test_no_supported_relation_is_a_semantic_gap_not_failure() -> None:
  no_relation = {
    "entities": [],
    "relations": [],
    "gaps": [{
      "code": "NO_SUPPORTED_CHILD_RELATION",
      "description": "The scoped text does not assert a basin-child relation.",
    }],
  }
  runner = runner_with(no_relation)

  assert runner.run(context()) == BuildOutcome.COMPLETED_WITH_GAPS


def test_runner_sets_graph_version_only_after_publication() -> None:
  build_context = context()
  store = InMemoryGraphStore()
  runner = ScopedExtractionRunner(
    provider=FakeDocIntelProvider([page()]),
    extractor=PageFactExtractor(
      client=SequenceExtractionClient([valid_extraction()])
    ),
    publisher=GraphPublisher(store=store),
  )

  outcome = runner.run(build_context)

  current = build_context.current_record()
  assert outcome == BuildOutcome.COMPLETED
  assert current.graph_version_id is not None
  assert store.completed_version(
    tenant_id="12",
    graph_version_id=current.graph_version_id,
    scope_fingerprint=current.scope_fingerprint,
  ) is not None


class SequenceExtractionClient:
  def __init__(self, responses):
    self.responses = list(responses)
    self.repair_flags: list[bool] = []

  def extract(self, unit, *, repair, previous_error):
    self.repair_flags.append(repair)
    return self.responses.pop(0)


class FakeDocIntelProvider:
  def __init__(self, pages):
    self.pages = pages

  def iter_pages(self, build):
    yield from self.pages


def runner_with(response):
  return ScopedExtractionRunner(
    provider=FakeDocIntelProvider([page()]),
    extractor=PageFactExtractor(client=SequenceExtractionClient([response])),
  )


def context() -> BuildContext:
  repository = InMemoryBuildRepository()
  record = repository.start_or_reuse(scope(), now=now())
  claimed = repository.claim(
    record.build_id,
    tenant_id="12",
    worker_id="worker-1",
    now=now(),
    lease_duration=__import__("datetime").timedelta(minutes=1),
  )
  return BuildContext(
    record=claimed,
    repository=repository,
    worker_id="worker-1",
    lease_duration=__import__("datetime").timedelta(minutes=1),
    clock=now,
  )


def page() -> ScopedPage:
  return ScopedPage(
    tenant_id="12",
    document_id="doc-1",
    version=3,
    content_hash=HASH_A,
    page_no=1,
    page_text="红河盆地包括北部凹陷。",
    chunks=(
      ScopedChunk(
        chunk_id="chunk-1",
        page_no=1,
        chunk_text="红河盆地包括北部凹陷。",
      ),
    ),
  )


def valid_extraction():
  return {
    "entities": [
      {
        "ref": "e1",
        "entity_type": "BASIN",
        "original_mention": "红河盆地",
        "display_name": "红河盆地",
        "aliases": [],
        "evidence_quote": "红河盆地包括北部凹陷",
      },
      {
        "ref": "e2",
        "entity_type": "DEPRESSION",
        "original_mention": "北部凹陷",
        "display_name": "北部凹陷",
        "aliases": [],
        "evidence_quote": "红河盆地包括北部凹陷",
      },
    ],
    "relations": [{
      "source_ref": "e1",
      "relation_type": "HAS_PART",
      "target_ref": "e2",
      "evidence_quote": "红河盆地包括北部凹陷",
    }],
    "gaps": [],
  }


def scope():
  from k_graph_mcp.contracts import (
    AuthorizedScopeEnvelope,
    DocumentScopeItem,
    canonical_scope_fingerprint,
  )

  unsigned = AuthorizedScopeEnvelope(
    request_id="request-1",
    tenant_id="12",
    requested_by="42",
    project_id="project-1",
    document_group=(
      DocumentScopeItem(
        document_id="doc-1",
        version=3,
        content_hash=HASH_A,
      ),
    ),
  )
  return unsigned.model_copy(update={
    "scope_fingerprint": canonical_scope_fingerprint(unsigned),
  })


def now():
  return datetime(2026, 7, 24, tzinfo=timezone.utc)
