"""Conservative structured extraction for BasinComparator phase-one facts."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import StrEnum
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import GraphEntityType, GraphRelationType
from .docintel import HttpDocIntelProvider, ScopedPage, SourceInvariantError
from .lifecycle import BuildContext, BuildOutcome


class ExtractionFailureCategory(StrEnum):
  PARSE = "PARSE"
  SCHEMA = "SCHEMA"
  GROUNDING = "GROUNDING"


class ExtractionResponseParseError(ValueError):
  """Provider content was not a JSON object; response text is never retained."""

  def __init__(self, issue: str):
    self.issue = issue
    super().__init__(issue)


class GroundingValidationError(ValueError):
  def __init__(
    self,
    *,
    field: str,
    issue: str,
    candidate: str | None = None,
  ):
    self.field = field
    self.issue = issue
    self.candidate = candidate
    super().__init__(f"{field}: {issue}")


class ExtractionValidationError(RuntimeError):
  """Structured output remained invalid after the single repair attempt."""

  def __init__(
    self,
    category: ExtractionFailureCategory,
    diagnostic: dict[str, Any] | None = None,
  ):
    self.category = category
    self.diagnostic = diagnostic or {"category": category.value}
    super().__init__(
      "structured extraction failed validation after one repair attempt "
      f"(category={category.value})"
    )


class ExtractionModel(BaseModel):
  model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RawEntity(ExtractionModel):
  ref: str = Field(min_length=1)
  entity_type: GraphEntityType
  original_mention: str = Field(min_length=1)
  display_name: str = Field(min_length=1)
  aliases: tuple[str, ...] = ()
  evidence_quote: str = Field(min_length=1, max_length=500)


class RawRelation(ExtractionModel):
  source_ref: str = Field(min_length=1)
  relation_type: GraphRelationType
  target_ref: str = Field(min_length=1)
  evidence_quote: str = Field(min_length=1, max_length=500)


class RawGap(ExtractionModel):
  code: str = Field(min_length=1)
  description: str = Field(min_length=1, max_length=500)
  evidence_quote: str | None = Field(default=None, max_length=500)


class RawExtraction(ExtractionModel):
  entities: tuple[RawEntity, ...] = ()
  relations: tuple[RawRelation, ...] = ()
  gaps: tuple[RawGap, ...] = ()


class ExtractedEntity(ExtractionModel):
  entity_key: str
  entity_type: str
  original_mention: str
  display_name: str
  aliases: tuple[str, ...]


class ExtractedRelation(ExtractionModel):
  relation_key: str
  source_entity_key: str
  source_entity_type: str
  relation_type: str
  target_entity_key: str
  target_entity_type: str


class ExtractedEvidence(ExtractionModel):
  evidence_key: str
  document_id: str
  document_version: int
  document_content_hash: str
  page_no: int
  chunk_id: str | None
  source_locator: str
  bounded_quote: str
  subject_kind: str
  subject_key: str


class ExtractedGap(ExtractionModel):
  code: str
  description: str
  evidence_quote: str | None = None
  diagnostic: dict[str, Any] | None = None


class ExtractedUnitResult(ExtractionModel):
  entities: tuple[ExtractedEntity, ...]
  relations: tuple[ExtractedRelation, ...]
  evidence: tuple[ExtractedEvidence, ...]
  gaps: tuple[ExtractedGap, ...]


class SourceUnit(ExtractionModel):
  tenant_id: str
  document_id: str
  version: int
  content_hash: str
  page_no: int
  chunk_id: str | None
  segment_index: int
  text: str

  @property
  def unit_id(self) -> str:
    location = self.chunk_id if self.chunk_id is not None else "page"
    return (
      f"{self.document_id}/v{self.version}/p{self.page_no}/"
      f"{location}/s{self.segment_index}"
    )

  @property
  def source_locator(self) -> str:
    base = (
      f"document:{self.document_id}/version:{self.version}/page:{self.page_no}"
    )
    if self.chunk_id is not None:
      base += f"/chunk:{self.chunk_id}"
    return f"{base}/segment:{self.segment_index}"


class StructuredExtractionClient(Protocol):
  def extract(
    self,
    unit: SourceUnit,
    *,
    repair: bool,
    previous_error: str | None,
  ) -> dict[str, Any]: ...


class GraphPublisherProtocol(Protocol):
  def publish(
    self,
    build: Any,
    outcome: BuildOutcome,
  ) -> str: ...


class PageFactExtractor:
  def __init__(self, *, client: StructuredExtractionClient):
    self._client = client

  def extract(
    self,
    source: ScopedPage | SourceUnit,
  ) -> ExtractedUnitResult:
    unit = source if isinstance(source, SourceUnit) else source_units(source)[0]
    previous_error: str | None = None
    failure_category = ExtractionFailureCategory.SCHEMA
    failure_detail: dict[str, Any] = {
      "field": "response",
      "issue": "invalid_schema",
    }
    for repair in (False, True):
      try:
        raw_value = self._client.extract(
          unit,
          repair=repair,
          previous_error=previous_error,
        )
        raw = RawExtraction.model_validate(raw_value)
        return self._validate_and_transform(unit, raw)
      except ExtractionResponseParseError as exception:
        failure_category = ExtractionFailureCategory.PARSE
        failure_detail = {"field": "response", "issue": exception.issue}
      except ValidationError as exception:
        failure_category = ExtractionFailureCategory.SCHEMA
        error = exception.errors(include_input=False)[0]
        failure_detail = {
          "field": ".".join(str(part) for part in error["loc"]),
          "issue": str(error["type"]),
        }
      except GroundingValidationError as exception:
        failure_category = ExtractionFailureCategory.GROUNDING
        failure_detail = {
          "field": exception.field,
          "issue": exception.issue,
        }
        if exception.candidate is not None:
          failure_detail["candidate"] = exception.candidate
      except ValueError:
        failure_category = ExtractionFailureCategory.GROUNDING
        failure_detail = {
          "field": "extraction",
          "issue": "provenance_invariant",
        }
      previous_error = (
        f"category={failure_category.value}; "
        f"field={failure_detail['field']}; "
        f"issue={failure_detail['issue']}"
      )
    raise ExtractionValidationError(
      failure_category,
      {
        "category": failure_category.value,
        **failure_detail,
        "document_id": unit.document_id,
        "document_version": unit.version,
        "page_no": unit.page_no,
        "unit_id": unit.unit_id,
      },
    )

  def _validate_and_transform(
    self,
    unit: SourceUnit,
    raw: RawExtraction,
  ) -> ExtractedUnitResult:
    entity_by_ref: dict[str, RawEntity] = {}
    entities: list[ExtractedEntity] = []
    evidence: list[ExtractedEvidence] = []
    gaps: list[ExtractedGap] = []
    for item in raw.entities:
      try:
        if item.ref in entity_by_ref:
          raise GroundingValidationError(
            field="entities.ref",
            issue="duplicate_ref",
            candidate=_safe_candidate(item.ref),
          )
        _require_grounded(
          unit.text,
          item.original_mention,
          field="entities.original_mention",
          expose_candidate=True,
        )
        _require_grounded(
          unit.text,
          item.display_name,
          field="entities.display_name",
          expose_candidate=True,
        )
        _require_grounded(
          unit.text,
          item.evidence_quote,
          field="entities.evidence_quote",
        )
        if item.original_mention not in item.evidence_quote:
          raise GroundingValidationError(
            field="entities.evidence_quote",
            issue="missing_original_mention",
          )
        for alias in item.aliases:
          _require_grounded(
            unit.text,
            alias,
            field="entities.aliases",
            expose_candidate=True,
          )
      except GroundingValidationError as exception:
        gaps.append(_rejected_candidate_gap(unit, exception))
        continue
      entity_by_ref[item.ref] = item
      entity_key = _stable_key(
        "entity",
        unit.tenant_id,
        item.entity_type.value,
        item.display_name,
      )
      entities.append(ExtractedEntity(
        entity_key=entity_key,
        entity_type=item.entity_type.value,
        original_mention=item.original_mention,
        display_name=item.display_name,
        aliases=item.aliases,
      ))
      evidence.append(_evidence(
        unit,
        subject_kind="ENTITY",
        subject_key=entity_key,
        quote=item.evidence_quote,
      ))

    relations: list[ExtractedRelation] = []
    for item in raw.relations:
      source = entity_by_ref.get(item.source_ref)
      target = entity_by_ref.get(item.target_ref)
      try:
        if source is None or target is None:
          raise GroundingValidationError(
            field="relations.refs",
            issue="rejected_or_missing_entity_ref",
          )
        if (
          source.entity_type != GraphEntityType.BASIN
          or target.entity_type not in {
            GraphEntityType.SAG,
            GraphEntityType.DEPRESSION,
          }
        ):
          raise GroundingValidationError(
            field="relations.relation_type",
            issue="unsupported_direction",
          )
        _require_grounded(
          unit.text,
          item.evidence_quote,
          field="relations.evidence_quote",
        )
        if (
          source.original_mention not in item.evidence_quote
          or target.original_mention not in item.evidence_quote
        ):
          raise GroundingValidationError(
            field="relations.evidence_quote",
            issue="missing_relation_mentions",
          )
      except GroundingValidationError as exception:
        gaps.append(_rejected_candidate_gap(unit, exception))
        continue
      source_key = _stable_key(
        "entity",
        unit.tenant_id,
        source.entity_type.value,
        source.display_name,
      )
      target_key = _stable_key(
        "entity",
        unit.tenant_id,
        target.entity_type.value,
        target.display_name,
      )
      relation_key = _stable_key(
        "relation",
        source_key,
        item.relation_type.value,
        target_key,
      )
      relations.append(ExtractedRelation(
        relation_key=relation_key,
        source_entity_key=source_key,
        source_entity_type=source.entity_type.value,
        relation_type=item.relation_type.value,
        target_entity_key=target_key,
        target_entity_type=target.entity_type.value,
      ))
      evidence.append(_evidence(
        unit,
        subject_kind="RELATION",
        subject_key=relation_key,
        quote=item.evidence_quote,
      ))

    gaps.extend(
      ExtractedGap(
        code=item.code,
        description=item.description,
        evidence_quote=item.evidence_quote,
      )
      for item in raw.gaps
    )
    for gap in gaps:
      if gap.evidence_quote is not None:
        _require_grounded(
          unit.text,
          gap.evidence_quote,
          field="gaps.evidence_quote",
        )
    if not relations and not gaps:
      gaps.append(ExtractedGap(
        code="NO_SUPPORTED_CHILD_RELATION",
        description=(
          "No source-grounded Basin HAS_PART Sag/Depression relation was "
          "found in this scoped source unit."
        ),
      ))
    return ExtractedUnitResult(
      entities=tuple(entities),
      relations=tuple(relations),
      evidence=tuple(evidence),
      gaps=tuple(gaps),
    )


class ScopedExtractionRunner:
  def __init__(
    self,
    *,
    provider: HttpDocIntelProvider,
    extractor: PageFactExtractor | None = None,
    extractor_factory: Callable[[Any], PageFactExtractor] | None = None,
    max_source_chars: int = 24_000,
    overlap_chars: int = 500,
    publisher: GraphPublisherProtocol | None = None,
  ):
    if extractor is None and extractor_factory is None:
      raise ValueError("extractor or extractor_factory is required")
    if max_source_chars < 1:
      raise ValueError("max_source_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_source_chars:
      raise ValueError("overlap_chars must be smaller than max_source_chars")
    self._provider = provider
    self._extractor = extractor
    self._extractor_factory = extractor_factory
    self._max_source_chars = max_source_chars
    self._overlap_chars = overlap_chars
    self._publisher = publisher

  def run(self, context: BuildContext) -> BuildOutcome:
    extractor = (
      self._extractor_factory(context.record)
      if self._extractor_factory is not None
      else self._extractor
    )
    if extractor is None:
      raise RuntimeError("extractor is not configured")
    page_count = 0
    relation_count = 0
    gap_count = 0
    valid_unit_count = 0
    last_extraction_diagnostic: dict[str, Any] | None = None
    for page in self._provider.iter_pages(context.record):
      page_count += 1
      for unit in source_units(
        page,
        max_chars=self._max_source_chars,
        overlap_chars=self._overlap_chars,
      ):
        context.raise_if_cancelled()
        saved = context.checkpoint_result(unit.unit_id)
        if saved is None:
          try:
            result = extractor.extract(unit)
            valid_unit_count += 1
          except ExtractionValidationError as exception:
            last_extraction_diagnostic = exception.diagnostic
            result = ExtractedUnitResult(
              entities=(),
              relations=(),
              evidence=(),
              gaps=(ExtractedGap(
                code="UNIT_EXTRACTION_REJECTED",
                description=(
                  f"{exception.diagnostic.get('field', 'response')}: "
                  f"{exception.diagnostic.get('issue', 'invalid_output')}"
                ),
                diagnostic=exception.diagnostic,
              ),),
            )
          context.checkpoint(unit.unit_id, result.model_dump(mode="json"))
        else:
          result = ExtractedUnitResult.model_validate(saved)
          rejected_gap = next((
            gap
            for gap in result.gaps
            if gap.code == "UNIT_EXTRACTION_REJECTED"
          ), None)
          if rejected_gap is None:
            valid_unit_count += 1
          else:
            last_extraction_diagnostic = rejected_gap.diagnostic
        relation_count += len(result.relations)
        gap_count += len(result.gaps)
    if page_count == 0:
      raise SourceInvariantError("DocIntel returned no normalized pages")
    if valid_unit_count == 0 and last_extraction_diagnostic is not None:
      raise ExtractionValidationError(
        ExtractionFailureCategory(
          last_extraction_diagnostic.get("category", "SCHEMA")
        ),
        last_extraction_diagnostic,
      )
    outcome = (
      BuildOutcome.COMPLETED_WITH_GAPS
      if relation_count == 0 or gap_count > 0
      else BuildOutcome.COMPLETED
    )
    if self._publisher is not None:
      context.raise_if_cancelled()
      graph_version_id = self._publisher.publish(
        context.current_record(),
        outcome,
      )
      context.set_graph_version(graph_version_id)
    return outcome


class OpenAIStructuredExtractionClient:
  """Provider-aware structured-output adapter; tests inject a fake client."""

  def __init__(
    self,
    *,
    client: Any,
    model: str,
    provider: str | None = None,
    base_url: str | None = None,
  ):
    if not model or not model.strip():
      raise ValueError("model is required")
    self._client = client
    self._model = model
    self._provider = provider
    self._base_url = base_url

  def extract(
    self,
    unit: SourceUnit,
    *,
    repair: bool,
    previous_error: str | None,
  ) -> dict[str, Any]:
    schema = json.dumps(
      RawExtraction.model_json_schema(),
      ensure_ascii=False,
      separators=(",", ":"),
    )
    system = (
      "Extract only source-grounded BasinComparator facts. Allowed entities: "
      "BASIN, SAG, DEPRESSION. Allowed directed relation: BASIN HAS_PART "
      "SAG/DEPRESSION. Co-occurrence is not relation evidence. Return only one "
      "JSON object matching the JSON Schema below, without Markdown or prose. "
      "Every original_mention, display_name, alias, and evidence_quote must be "
      "an exact substring of the supplied source text. Every evidence_quote "
      "must contain its referenced exact mentions. Never infer beyond the "
      f"supplied text.\nJSON Schema:\n{schema}"
    )
    if repair:
      system += (
        " Repair the prior invalid JSON result using the schema and grounding "
        f"rules. Validation error: {previous_error}"
      )
    request: dict[str, Any] = {
      "model": self._model,
      "temperature": 0,
      "messages": [
        {"role": "system", "content": system},
        {
          "role": "user",
          "content": (
            f"Source locator: {unit.source_locator}\n"
            f"Source text:\n{unit.text}"
          ),
        },
      ],
    }
    if _uses_portable_json_object(self._provider, self._base_url):
      request["response_format"] = {"type": "json_object"}
      if _is_qwen(self._provider, self._base_url):
        request["extra_body"] = {"enable_thinking": False}
    else:
      request["response_format"] = {
        "type": "json_schema",
        "json_schema": {
          "name": "basin_graph_extraction",
          "strict": True,
          "schema": RawExtraction.model_json_schema(),
        },
      }
    response = self._client.chat.completions.create(**request)
    content = response.choices[0].message.content
    try:
      value = json.loads(content)
    except (json.JSONDecodeError, TypeError):
      raise ExtractionResponseParseError(
        "invalid_json"
      ) from None
    if not isinstance(value, dict):
      raise ExtractionResponseParseError(
        "not_json_object"
      )
    return value


def _uses_portable_json_object(
  provider: str | None,
  base_url: str | None,
) -> bool:
  identity = f"{provider or ''} {base_url or ''}".lower()
  return "deepseek" in identity or "dashscope" in identity


def _is_qwen(provider: str | None, base_url: str | None) -> bool:
  identity = f"{provider or ''} {base_url or ''}".lower()
  return "qwen" in identity or "dashscope" in identity


def source_units(
  page: ScopedPage,
  *,
  max_chars: int = 24_000,
  overlap_chars: int = 500,
) -> tuple[SourceUnit, ...]:
  sources = [
    (chunk.chunk_id, chunk.chunk_text)
    for chunk in page.chunks
    if chunk.chunk_text is not None and chunk.chunk_text.strip()
  ]
  if not sources:
    sources = [(None, page.page_text)]
  units: list[SourceUnit] = []
  for chunk_id, text in sources:
    for index, segment in enumerate(
      _segments(text, max_chars=max_chars, overlap_chars=overlap_chars)
    ):
      units.append(SourceUnit(
        tenant_id=page.tenant_id,
        document_id=page.document_id,
        version=page.version,
        content_hash=page.content_hash,
        page_no=page.page_no,
        chunk_id=chunk_id,
        segment_index=index,
        text=segment,
      ))
  return tuple(units)


def _segments(
  text: str,
  *,
  max_chars: int,
  overlap_chars: int,
) -> tuple[str, ...]:
  if len(text) <= max_chars:
    return (text,)
  step = max_chars - overlap_chars
  return tuple(
    text[start:start + max_chars]
    for start in range(0, len(text), step)
    if text[start:start + max_chars]
  )


def _require_grounded(
  source: str,
  value: str,
  *,
  field: str,
  expose_candidate: bool = False,
) -> None:
  if value not in source:
    raise GroundingValidationError(
      field=field,
      issue="not_exact_source_substring",
      candidate=_safe_candidate(value) if expose_candidate else None,
    )


def _safe_candidate(value: str) -> str | None:
  normalized = unicodedata.normalize("NFKC", value)
  normalized = re.sub(r"\s+", " ", normalized).strip()
  if not normalized:
    return None
  return normalized[:48]


def _rejected_candidate_gap(
  unit: SourceUnit,
  exception: GroundingValidationError,
) -> ExtractedGap:
  diagnostic: dict[str, Any] = {
    "category": ExtractionFailureCategory.GROUNDING.value,
    "field": exception.field,
    "issue": exception.issue,
    "document_id": unit.document_id,
    "document_version": unit.version,
    "page_no": unit.page_no,
    "unit_id": unit.unit_id,
  }
  if exception.candidate is not None:
    diagnostic["candidate"] = exception.candidate
  return ExtractedGap(
    code="REJECTED_EXTRACTION_CANDIDATE",
    description=(
      f"{exception.field}: {exception.issue}"
    ),
    diagnostic=diagnostic,
  )


def _stable_key(*parts: str) -> str:
  payload = "\0".join(part.strip() for part in parts)
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence(
  unit: SourceUnit,
  *,
  subject_kind: str,
  subject_key: str,
  quote: str,
) -> ExtractedEvidence:
  evidence_key = _stable_key(
    "evidence",
    unit.document_id,
    str(unit.version),
    str(unit.page_no),
    unit.chunk_id or "",
    subject_kind,
    subject_key,
    quote,
  )
  return ExtractedEvidence(
    evidence_key=evidence_key,
    document_id=unit.document_id,
    document_version=unit.version,
    document_content_hash=unit.content_hash,
    page_no=unit.page_no,
    chunk_id=unit.chunk_id,
    source_locator=unit.source_locator,
    bounded_quote=quote,
    subject_kind=subject_kind,
    subject_key=subject_key,
  )
