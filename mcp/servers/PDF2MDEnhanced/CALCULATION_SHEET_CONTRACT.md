# Calculation sheet extraction, version 1

Calculation sheets organize inputs, equations, branches, checks, references and notes.
Their ruled panels are not necessarily cross-indexed data records. Never pair the
left and right panels merely because text shares a vertical coordinate.

## Routing and calls

The existing VLM table semantic response now carries `table_kind`:
`data_table`, `calculation_sheet`, `mixed`, or `uncertain`, plus exact source quotes
in `classification_evidence`. The image supplies type evidence; a title or the
presence of one formula alone is insufficient. Invalid/foreign/ambiguous source
quotes downgrade the classification to uncertain.

The existing semantic call classifies tables. A validated `calculation_sheet`
classification dispatches current object-scoped OCR content to the shared text-only semantic stage.
Source persistence precedes model organization. Human image transcription uses the selected engine
and the existing source-first contract; its source is checked before `parse_calculation_sheet`.
Already source-validated proposals need no additional extraction.

An explicitly configured `vlm_config.table_analysis_max_model_calls` remains a
shared per-page logical analysis budget (integers 0..8, zero disables analysis).
An explicit physical cap also retains the fixed-budget behavior. Neither cap is
silently expanded. Manual processing retains its existing budget contract.

With neither cap configured, automatic calculation completion reserves one semantic call per actual
source batch. It reuses current object-scoped OCR content without an additional image transcription
call. Explicit caller caps remain fixed. Sources are saved as `existing_ocr` artifacts before semantic
work; empty content and failed source persistence remain unresolved, without image-model fallback.

Human calculation image requests default to configured GLM-OCR transcription. The existing review
engine choice is carried in context as `transcription_engine=ocr|vlm`; only explicit `vlm` requests
use VLM transcription. OCR performs one attempt within the shared physical budget, reports its own
model-call count, and never falls back to VLM on error. Classification, when needed, remains a separate
bounded existing call. Both choices preserve image identity and the existing source-first handoff.

Task-backed asynchronous extraction hands off the existing worker before semantic
processing. Its deadline grows only with concrete reserved stage calls; polling
never starts another worker. Ordinary pages retain their synchronous lifecycle.

Dedicated extraction is at most min(provider max_tokens, 16384) output tokens.
Single-page metadata has the same cap, replacing its former 2048 cap. No formula
execution or repeated calculation-item repair loop is added. A recognized sheet
with omitted items requires dedicated extraction, never a successful empty result.

Integrated entry points:

- Full GLM upload: existing identity-bound table VLM semantic pass and dedicated calculation call, before output
  pandas/formula processing. Prior generated context is excluded from classification
  input; OCR supports classification, while object-image transcription supplies the calculation source.
- Single-page GLM extraction with descriptions enabled: defer grid normalization
  until the existing metadata call classifies the table. Data tables then use the
  existing normalization; calculation/mixed/uncertain objects retain original text.
- Direct VLM table, compact, region, layout-structured and dual-output responses:
  additive classification instructions and validated metadata survive normalization;
  incomplete calculation proposals enter the same budgeted dedicated completion.
  A compact retry consumes budget before dedicated completion.

Native deterministic extraction and descriptions-disabled GLM paths do not gain
implicit model calls. Object-crop HTML-only recovery remains a structural operation;
it does not by itself provide calculation classification. The normal upload semantic
pass provides that classification. Old responses without `table_kind` retain the
legacy contract; absence is not evidence of successful classification.

## Derived output

`markdown`/`raw_html` remain original content. `calculation_sheet.render_markdown`
is an independent two-column Item/step–Content projection with section headings.
It is not a numeric lookup matrix. First-page promotion includes the new fields.
Membership must explicitly adopt the new field before its UI will show this view.

A proposed section has a title and ordered items. Each item has:

- `kind`: input, formula, branch, check, reference, or note;
- `name`, optional `symbol`, `latex`, `unit`;
- `conditions`, `checks`, `references` as source strings;
- `sources`: exact unique quotes from `calculation_source.text`;
- optional `bbox` in normalized page-image coordinates, bounded by the table region.

The parser produces item IDs, exact source content, source SHA-256, decoded-text
ranges, table identity, and location scope (`item` or `table`). Missing item geometry
is explicit in diagnostics. Text ranges refer to exported `source_text`, not HTML
byte offsets. Repeated short quotes are rejected; use a longer unique source quote.
HTML text extraction preserves cell/paragraph breaks and LaTeX without reading spans
or invoking pandas. It does not establish original-image accuracy.

All scalar/list fields must occur literally in the cited source quotes. Generated
section titles follow the description language; exact source titles remain unchanged. Formula
syntax reuses the existing balanced-brace/environment validator. Branch conditions
and check expressions are required for their corresponding item kinds. Every
non-whitespace source character must be covered; omissions remain unresolved. Image
versus OCR discrepancies are retained and must not silently rewrite the source.
External figure references remain references; no values or dependencies are invented.

## Quality and downstream guard

`validation_status=source_validated` means source consistency only. All first-version
calculation sheets retain `quality_status=needs_review`, `image_verified=false`, and
`source_bound_not_image_verified`. Invalid items, omitted content and reported image
conflicts yield `validation_status=unresolved`. `table_content_quality` is separate
from name/description `semantic_status` and layout `EXTRACTED`/recovery status.

Calculation/mixed/uncertain objects carry empty `lookup_sections`, unavailable lookup
status, and review flags. Single-page grid output fields remain empty. Query enhancement
rejects these types before pandas or provider construction. Consumers must propagate
`table_kind`; dropping it defeats the additive guard. Do not publish this two-column
view through a legacy consumer that treats any nonempty table rows as queryable.

Bounds: at most 100000 source characters, 200000 serialized proposal characters,
100 sections, 500 items, 50 source quotes per item, and 20 classification quotes.
Uncertain/mixed objects preserve source and require review; automatic mixed-region
partitioning remains out of scope. The explicit processing extension below supplies
bounded cross-page proposals without database writes.

## Explicit processing extension (2026-09-13)

The existing `extract_page_tables` tool accepts `table_kind_hint` and
`processing_mode`, with a validated `context.calculation_request`. See the
[frozen wire contract](../../../docs/plans/2026-09-13-calculation-sheet-mcp-contract-draft.md)
and the shared `tests/fixtures/calculation_processing_contract.json` fixture.

`organize_existing` uses only supplied text and one explicit text-model call.
`reextract` reads one isolated object image, with a manual type constraint.
`auto` performs image classification and item extraction; uncertain/continuation
results may receive one joint review with at most one object from each adjacent
page, using base64 `image_data`. Both calls share the existing logical budget.
Without context or remaining budget the relation stays pending. Legacy upload and
single-page semantic responses can request this follow-up through `continuation`;
Membership must provide identities/context and perform the automatic scheduling.

The current image is either a caller-authorized object crop (`object_crop=true`)
or a region (`calculation_request.bbox`) cropped from a full PDF whose SHA-256 and
page number are checked. For incoming crops, Membership must verify the original
PDF identity before dispatch; the MCP cannot reconstruct a whole PDF hash from an
object image. The returned `image_sha256` identifies the actual processed crop.
Item geometry from this extension is `normalized_object`, not page coordinates.
Text-only organization removes model-proposed image geometry altogether.

Classification type and content validation remain separate. Manual type is never
overwritten by model output; incomplete items retain calculation-sheet type and
review quality. Optional item `value` is a source-bound string, retaining original
precision or an intentional empty value. All model transcriptions remain
`image_verified=false`. Ordinary tables use existing normalization; calculation
JSON never requires a grid. Type evidence diagnostics now distinguish invalid kind,
missing/mismatched/ambiguous evidence and model uncertainty. Missing legacy type
is explicitly `classification_not_run`, preserving the old type default.

Every validated identity is echoed on the selected item and response root. Results
are `needs_review` or `failed`, retain the selected object and supplied content,
and never publish. Foreign/duplicate identities, invalid scope and changed table
numbers cannot become authoritative relations. Joint review also returns separate
adjacent classifications and proposed next-page relations without copying items.
Generic model outputs cannot assert manual provenance or trusted document identity.

The configured logical budget does not count provider retries/fallbacks as
separate logical calls. For the new processing entry only, a separate HTTPX
pre-send hook enforces the physical cap (normally 2 for text organization and 4
for automatic/image processing). It counts redirects and all fallback attempts;
SDK and outer retries are disabled. `table_analysis_max_physical_requests` may
lower, but not raise, that cap. Response budget fields report actual attempted
sends and the cap. A follow-up RPC receives a new budget and must consume its
reserved allowance in Membership's run manifest. Legacy client behavior is
unchanged. Provider timeouts/errors are safe diagnostic
codes, not transcripts. Cancellation propagates where received; cancellation of
an executor-backed RPC cannot forcibly abort an already in-flight synchronous
provider request. No MCP path writes to Membership or publishes a late result;
Membership must keep its existing task/version cancellation protection.

## Validation

Offline regression command:

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_calculation_sheet.py
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_calculation_processing.py
```

Offline tests do not prove VLM recognition, formula fidelity, deployment or Membership
integration. See the dated execution report for independently recorded evidence.
