"""Conservative structured extraction for BasinComparator phase-one facts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import GraphEntityType, GraphRelationType
from .docintel import HttpDocIntelProvider, ScopedPage, SourceInvariantError
from .lifecycle import BuildContext, BuildOutcome


class ExtractionValidationError(RuntimeError):
  """Structured output remained invalid after the single repair attempt."""


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
    for repair in (False, True):
      raw_value = self._client.extract(
        unit,
        repair=repair,
        previous_error=previous_error,
      )
      try:
        raw = RawExtraction.model_validate(raw_value)
        return self._validate_and_transform(unit, raw)
      except (ValidationError, ValueError) as exception:
        previous_error = str(exception)
    raise ExtractionValidationError(
      "structured extraction failed validation after one repair attempt"
    )

  def _validate_and_transform(
    self,
    unit: SourceUnit,
    raw: RawExtraction,
  ) -> ExtractedUnitResult:
    entity_by_ref: dict[str, RawEntity] = {}
    entities: list[ExtractedEntity] = []
    evidence: list[ExtractedEvidence] = []
    for item in raw.entities:
      if item.ref in entity_by_ref:
        raise ValueError("entity refs must be unique")
      _require_grounded(unit.text, item.original_mention, "entity mention")
      _require_grounded(unit.text, item.display_name, "entity display name")
      _require_grounded(unit.text, item.evidence_quote, "entity evidence")
      if item.original_mention not in item.evidence_quote:
        raise ValueError("entity evidence must contain the original mention")
      for alias in item.aliases:
        _require_grounded(unit.text, alias, "entity alias")
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
      if source is None or target is None:
        raise ValueError("relation refs must resolve to entities in the unit")
      if (
        source.entity_type != GraphEntityType.BASIN
        or target.entity_type not in {
          GraphEntityType.SAG,
          GraphEntityType.DEPRESSION,
        }
      ):
        raise ValueError(
          "HAS_PART must point from BASIN to SAG or DEPRESSION"
        )
      _require_grounded(unit.text, item.evidence_quote, "relation evidence")
      if (
        source.original_mention not in item.evidence_quote
        or target.original_mention not in item.evidence_quote
      ):
        raise ValueError(
          "relation evidence must contain both original entity mentions"
        )
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

    gaps = [
      ExtractedGap(
        code=item.code,
        description=item.description,
        evidence_quote=item.evidence_quote,
      )
      for item in raw.gaps
    ]
    for gap in gaps:
      if gap.evidence_quote is not None:
        _require_grounded(unit.text, gap.evidence_quote, "gap evidence")
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
    extractor: PageFactExtractor,
    max_source_chars: int = 24_000,
    overlap_chars: int = 500,
    publisher: GraphPublisherProtocol | None = None,
  ):
    if max_source_chars < 1:
      raise ValueError("max_source_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_source_chars:
      raise ValueError("overlap_chars must be smaller than max_source_chars")
    self._provider = provider
    self._extractor = extractor
    self._max_source_chars = max_source_chars
    self._overlap_chars = overlap_chars
    self._publisher = publisher

  def run(self, context: BuildContext) -> BuildOutcome:
    page_count = 0
    relation_count = 0
    gap_count = 0
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
          result = self._extractor.extract(unit)
          context.checkpoint(unit.unit_id, result.model_dump(mode="json"))
        else:
          result = ExtractedUnitResult.model_validate(saved)
        relation_count += len(result.relations)
        gap_count += len(result.gaps)
    if page_count == 0:
      raise SourceInvariantError("DocIntel returned no normalized pages")
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
  """OpenAI-compatible JSON-schema adapter; tests inject a fake client."""

  def __init__(self, *, client: Any, model: str):
    if not model or not model.strip():
      raise ValueError("model is required")
    self._client = client
    self._model = model

  def extract(
    self,
    unit: SourceUnit,
    *,
    repair: bool,
    previous_error: str | None,
  ) -> dict[str, Any]:
    system = (
      "Extract only source-grounded BasinComparator facts. Allowed entities: "
      "BASIN, SAG, DEPRESSION. Allowed directed relation: BASIN HAS_PART "
      "SAG/DEPRESSION. Co-occurrence is not relation evidence. Copy exact "
      "bounded source quotes and never infer beyond the supplied text."
    )
    if repair:
      system += (
        " Repair the prior invalid JSON result using the schema and grounding "
        f"rules. Validation error: {previous_error}"
      )
    response = self._client.chat.completions.create(
      model=self._model,
      temperature=0,
      messages=[
        {"role": "system", "content": system},
        {
          "role": "user",
          "content": (
            f"Source locator: {unit.source_locator}\n"
            f"Source text:\n{unit.text}"
          ),
        },
      ],
      response_format={
        "type": "json_schema",
        "json_schema": {
          "name": "basin_graph_extraction",
          "strict": True,
          "schema": RawExtraction.model_json_schema(),
        },
      },
    )
    content = response.choices[0].message.content
    try:
      value = json.loads(content)
    except (json.JSONDecodeError, TypeError):
      return {"invalid_structured_response": content}
    return value


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


def _require_grounded(source: str, value: str, label: str) -> None:
  if value not in source:
    raise ValueError(f"{label} is not an exact substring of the source unit")


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
