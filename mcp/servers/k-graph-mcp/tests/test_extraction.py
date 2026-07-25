import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from k_graph_mcp.contracts import BuildStatus
from k_graph_mcp.docintel import ScopedChunk, ScopedPage
from k_graph_mcp.extraction import (
  ExtractionValidationError,
  ExtractionResponseParseError,
  OpenAIStructuredExtractionClient,
  PageFactExtractor,
  ScopedExtractionRunner,
  source_units,
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


def test_invalid_relation_is_isolated_without_discarding_valid_entities() -> None:
  invalid = valid_extraction()
  invalid["relations"][0]["evidence_quote"] = "红河盆地"
  client = SequenceExtractionClient([invalid, valid_extraction()])
  extractor = PageFactExtractor(client=client)

  result = extractor.extract(page())

  assert result.relations == ()
  assert len(result.entities) == 2
  assert result.gaps[0].diagnostic["field"] == "relations.evidence_quote"
  assert client.repair_flags == [False]


def test_invalid_entity_candidate_does_not_fail_the_unit() -> None:
  invalid = valid_extraction()
  invalid["entities"][0]["original_mention"] = "不存在的盆地"
  client = SequenceExtractionClient([invalid, invalid])

  result = PageFactExtractor(client=client).extract(page())

  assert len(result.entities) == 1
  assert result.gaps[0].diagnostic["field"] == "entities.original_mention"
  assert client.repair_flags == [False]


def test_exact_source_grounding_remains_required() -> None:
  invalid = valid_extraction()
  invalid["entities"][0]["display_name"] = "规范化红河盆地"
  result = PageFactExtractor(
    client=SequenceExtractionClient([invalid])
  ).extract(page())

  assert [item.display_name for item in result.entities] == ["北部凹陷"]
  assert result.relations == ()
  assert result.gaps[0].diagnostic == {
    "category": "GROUNDING",
    "field": "entities.display_name",
    "issue": "not_exact_source_substring",
    "candidate": "规范化红河盆地",
    "document_id": "doc-1",
    "document_version": 3,
    "page_no": 1,
    "unit_id": "doc-1/v3/p1/chunk-1/s0",
  }
  assert all(
    item.display_name != "规范化红河盆地"
    for item in result.entities
  )


def test_terminal_schema_failure_is_sanitized() -> None:
  marker = "sensitive-provider-output"
  client = SequenceExtractionClient([
    {"unexpected": marker},
    {"unexpected": marker},
  ])

  with pytest.raises(ExtractionValidationError) as caught:
    PageFactExtractor(client=client).extract(page())

  assert caught.value.category == "SCHEMA"
  assert marker not in str(caught.value)


def test_terminal_parse_failure_is_sanitized() -> None:
  client = RaisingExtractionClient(
    ExtractionResponseParseError("provider response is not valid JSON")
  )

  with pytest.raises(ExtractionValidationError) as caught:
    PageFactExtractor(client=client).extract(page())

  assert caught.value.category == "PARSE"
  assert str(caught.value).endswith("(category=PARSE)")


@pytest.mark.parametrize(
  ("provider", "base_url", "disable_thinking"),
  [
    ("Qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", True),
    ("DeepSeek", "https://api.deepseek.com/v1", False),
  ],
)
def test_json_object_providers_receive_portable_structured_request(
  provider,
  base_url,
  disable_thinking,
) -> None:
  client = CapturingOpenAIClient(valid_extraction())
  adapter = OpenAIStructuredExtractionClient(
    client=client,
    model="provider-model",
    provider=provider,
    base_url=base_url,
  )

  adapter.extract(source_units(page())[0], repair=False, previous_error=None)

  request = client.requests[0]
  assert request["response_format"] == {"type": "json_object"}
  assert ("extra_body" in request) is disable_thinking
  if disable_thinking:
    assert request["extra_body"] == {"enable_thinking": False}
  system = request["messages"][0]["content"]
  assert "JSON" in system
  assert '"entities"' in system
  assert "exact substring" in system


def test_native_openai_retains_strict_json_schema_request() -> None:
  client = CapturingOpenAIClient(valid_extraction())
  adapter = OpenAIStructuredExtractionClient(
    client=client,
    model="gpt-test",
    provider="OpenAI",
    base_url="https://api.openai.com/v1",
  )

  adapter.extract(source_units(page())[0], repair=False, previous_error=None)

  response_format = client.requests[0]["response_format"]
  assert response_format["type"] == "json_schema"
  assert response_format["json_schema"]["strict"] is True


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


def test_runner_resolves_extractor_for_the_current_build() -> None:
  build_context = context()
  client = SequenceExtractionClient([valid_extraction()])
  resolved_build_ids = []
  runner = ScopedExtractionRunner(
    provider=FakeDocIntelProvider([page()]),
    extractor_factory=lambda record: (
      resolved_build_ids.append(record.build_id)
      or PageFactExtractor(client=client)
    ),
  )

  assert runner.run(build_context) == BuildOutcome.COMPLETED
  assert resolved_build_ids == [build_context.record.build_id]


def test_runner_isolates_one_invalid_unit_and_publishes_partial_result() -> None:
  build_context = context()
  second_page = page().model_copy(update={
    "page_no": 2,
    "chunks": (
      ScopedChunk(
        chunk_id="chunk-2",
        page_no=2,
        chunk_text="红河盆地包括北部凹陷。",
      ),
    ),
  })
  runner = ScopedExtractionRunner(
    provider=FakeDocIntelProvider([page(), second_page]),
    extractor=PageFactExtractor(client=UnitSelectiveExtractionClient()),
  )

  outcome = runner.run(build_context)

  assert outcome == BuildOutcome.COMPLETED_WITH_GAPS
  rejected = build_context.checkpoint_result(
    "doc-1/v3/p1/chunk-1/s0"
  )
  valid = build_context.checkpoint_result(
    "doc-1/v3/p2/chunk-2/s0"
  )
  assert rejected["gaps"][0]["code"] == "UNIT_EXTRACTION_REJECTED"
  assert rejected["gaps"][0]["diagnostic"]["category"] == "PARSE"
  assert valid["relations"][0]["relation_type"] == "HAS_PART"


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


class RaisingExtractionClient:
  def __init__(self, exception):
    self.exception = exception

  def extract(self, unit, *, repair, previous_error):
    raise self.exception


class UnitSelectiveExtractionClient:
  def extract(self, unit, *, repair, previous_error):
    if unit.page_no == 1:
      raise ExtractionResponseParseError("invalid_json")
    return valid_extraction()


class CapturingOpenAIClient:
  def __init__(self, response):
    self.requests = []
    self.chat = SimpleNamespace(
      completions=SimpleNamespace(create=self._create),
    )
    self._content = json.dumps(response, ensure_ascii=False)

  def _create(self, **kwargs):
    self.requests.append(kwargs)
    return SimpleNamespace(
      choices=[
        SimpleNamespace(message=SimpleNamespace(content=self._content))
      ],
    )


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
