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
classification dispatches to `DynamicVLMClient.extract_calculation_sheet`, a separate
image call with one object reference and source hash. That method has a single
calculation-items schema (no metadata/classification schema). Its response is checked
by `parse_calculation_sheet`, which never invokes pandas. Already source-validated
inline proposals from compatible direct VLM responses need no extra extraction.

`vlm_config.table_analysis_max_model_calls` is a shared per-page **logical** analysis
budget, including classification and dedicated calls for all tables. Default 2 means
one classification plus one dedicated extraction; zero disables the table semantic
analysis, invalid values fail closed, and supported values are integers 0..8.
Subsequent calculation tables remain unresolved when that shared budget is spent.
Existing provider transport retries/fallbacks remain transport behavior; this logical
budget must not be described as a physical HTTP-request cap. The private live probe
used a separate hard physical-call cap and disabled SDK retries.

Dedicated extraction is at most min(provider max_tokens, 16384) output tokens.
Single-page metadata has the same cap, replacing its former 2048 cap. No formula
execution or repeated calculation-item repair loop is added. A recognized sheet
with omitted items requires dedicated extraction, never a successful empty result.

Integrated entry points:

- Full GLM upload: existing identity-bound table VLM semantic pass and dedicated calculation call, before output
  pandas/formula processing. Prior generated context is excluded from classification
  input; OCR content remains authoritative.
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
partitioning and cross-page calculation chaining are outside this first version.

## Validation

Offline regression command:

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_calculation_sheet.py
```

Offline tests do not prove VLM recognition, formula fidelity, deployment or Membership
integration. See the dated execution report for independently recorded evidence.
