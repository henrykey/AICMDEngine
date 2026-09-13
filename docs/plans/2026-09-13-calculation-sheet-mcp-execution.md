# Calculation sheet MCP execution record

Date: 2026-09-13

Status: MCP source implementation, focused verification and shared consumer
fixture verification complete; joint runtime acceptance remains pending.
No commit, image build, deployment, restart, external model call or document
write has been performed by this task.

## Verified baseline

- AICMDEngine: `main`, `3c0e91de0937b0cdd7e77deae15ae1a902a47824`;
  initially clean working tree.
- Membership: `57dc0f96ef665554adf500638a347fe10a037cff`; the two September 13
  calculation-sheet plans are untracked. No Membership files were changed.
- Running container: `pdf2md-enhanced-mcp`; image ID
  `sha256:edd1bf7c6f7bc425a41e6536957c24c924e9e6a8131adddf07eda070ea8e3ee0`.
  Created `2026-09-13T09:11:52.557380833Z`.
- SHA-256 matches between local source and `/app/PDF2MDEnhanced/` for
  `calculation_sheet.py`, `server.py`, `single_page_tools.py`,
  `page_processor.py`, and `vlm_client.py`. Only input/output directories are
  bind mounted; these source files are in the image.
- CodeGraph status reports the index up to date, with an older engine-version
  advisory. Callers of `apply_calculation_sheet` were checked. No source edit,
  index rebuild, container build/restart, model call, or document write occurred.

## P0 findings

The registered `server.extract_page_tables` forwards to
`single_page_tools.extract_page_tables_direct`. Neither signature has
`table_kind_hint`, a processing mode, or a dedicated adjacent-object contract.
Full-document and single-page semantic paths both use `apply_calculation_sheet`
and `complete_calculation_batch`.

`apply_calculation_sheet` catches classification validation failures and discards
their specific cause. Invalid type, missing evidence, foreign evidence and
ambiguous quotes all become `uncertain` / `classification_unresolved`. A model
proposal of `uncertain` has the same final reason. Existing saved metadata cannot
recover which of these happened. This is a confirmed diagnostic defect, not proof
of the historical model's original answer.

The specified task `task_24d4a51a7f8287f2` remains locally available. It is a
one-page crop task (`planned_pages=[1]`, `page_1.json`), with original object IDs
`p13-o003-table` and `p13-o006-table`. Both retain `uncertain` and
`classification_unresolved`. The crop filename is
`ASME_VIII2_2025_Complex_Table_Test_Set.pdf-p13_e5175e688d02.pdf`;
task source SHA-1 is `e5175e688d02e57cffa4bfe35b89722dcdc47b66`.
Task page 1 must not be confused with original PDF page 13. The crop is available
under the local output `uploads` directory; it is not the complete source PDF.

Client defaults are 2 logical table-analysis calls per page, timeout 60 seconds,
2 transport retries, and 4096 max tokens. Accepted logical budget is integer 0–8;
invalid values disable calls. These are source defaults, not a verified historical
request configuration or a physical request cap. The saved task metadata does not
contain `vlm_config`; actual model and request settings remain unverified.

## P1 producer/consumer mapping and open contract

Membership `ReviewAssistedExtractionService.buildContext` already sends
`tenant_id`, `doc_id`, `version`, `page_no`, `element_type`, `element_id`,
`table_pk`, and `layout_id`. A source hash and adjacent-object identity/image
bundle are not present in that builder. Use these existing identity names when
freezing the extension; do not introduce a competing document identity.

Membership `CalculationSheetContent.copy` preserves `table_kind`,
`table_kind_source`, `content_format`, `calculation_sheet`, `table_classification`,
`calculation_source`, and `table_content_quality`. It supplies
`content_format=calculation_sheet_json` for calculation sheets. This confirms
partial consumption, not a completed review/publish/UI workflow.

Before P2, the shared contract must settle:

1. A source hash with an explicit scope (PDF bytes, object image or OCR text),
   plus current-object identity echoed unchanged in results. The existing OCR
   `source_sha256` must not be mislabeled as the PDF hash.
2. Explicit automatic, organize-existing-content and image-reextract modes;
   manual type constraints must survive extraction and return as manual provenance.
3. Bounded adjacent objects with same-scope identities and images; relation
   proposals and pending-context diagnostics separate from authoritative links.
4. Classification reason codes distinct from content and continuation quality;
   preserve legacy fields and avoid uncalibrated percentage confidence.
5. Shared request/response fixtures consumed by both repositories. The current
   Membership baseline does not implement these new semantics.

These are open semantic requirements, not frozen or implemented wire fields.
No unilateral fallback or public tool was added.

## Validation and next gate

Baseline command:

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_calculation_sheet.py tests/test_pdf2md_enhanced_table_query.py
```

Result: **121 passed**, 64 existing configuration/dependency warnings.
This establishes the old contracts only; it does not validate planned behavior.

The user identified `GBT151-2026_Complex_Table_Test_Set.pdf` in category `test`.
Both complete PDFs were subsequently found under `/Users/kehongwei/Documents/GB/`.
Original-image inspection confirmed GBT151 table 8-5 on PDF page 7 (printed 66),
and table 8-6 on the next page is a different object. ASME pages 11–13 and GBT151
pages 7–9 were visually inspected for positive and negative annotations. Hashes,
annotation expectations and a concrete proposed wire contract are recorded in
[P1 contract draft](2026-09-13-calculation-sheet-mcp-contract-draft.md).

A read-only synthetic probe reproduced four distinct causes (invalid type,
missing evidence, foreign evidence, model uncertain) yielding the same
`classification_unresolved` reason. No production source has been changed.

The active Membership task `显示计算书表格类型` was located and read; its user
explicitly requested Membership plan execution. Sending it the P1 alignment
proposal was initially rejected by automatic approval review as potential
cross-task disclosure of internal paths/identity metadata. The user subsequently
explicitly authorized the message. Retrying through `send_message_to_thread`
succeeded, and the Membership task confirmed it read the draft. Its outgoing
reply was separately rejected by its automatic approval review, which requires
explicit coordination authorization in that task. No alternative delivery
mechanism was used. Membership document ID/version and stored PDF hash mapping
remain pending alongside mutual contract agreement.

Additional baseline validation: single-page tools, upload semantics and content
quality tests passed (255 tests). Including the separate remote MCP script in
pytest produced two setup errors because `jwt_token` is not a fixture; neither
remote test executed. These errors are not source-regression failures and are
not evidence of live MCP acceptance.

After explicit authorization in both tasks, Membership confirmed the request and
response fields and requested base64 `image_data` for adjacent images because the
containers do not share rendering paths. This was accepted and the P1 wire
contract frozen before production edits. The shared synthetic fixture now exists
at `tests/fixtures/calculation_processing_contract.json`; Membership copied it to
`membership-docs/src/test/resources/fixtures/calculation_processing_contract.json`.
Both files have SHA-256 `b21b6f68e41a12e4b777e465d3c1ba07d513225014a623feee638824d74a6c3e`.
The producer asserts the actual stubbed tool envelope equals `mcp_response`.
The consumer test `sharedProcessingFixturePreservesManualTypeAndOrganizesWithoutImageRead`
reads that envelope through its normalizer. Its current test XML reports
`CalculationSheetContractTest`: 9 tests, 0 failures/errors, timestamp
`2026-09-13T12:37:13.278Z`. This MCP task independently read the fixture hashes,
consumer test and XML; it did not run or modify Membership tests.

P6 additionally requires a concrete approved sample-copy/model-budget/runtime
procedure. No commit/push, deployment, model use, or canonical document mutation
is included in this execution record.

## Source implementation and verification

| Goal | Current evidence |
| --- | --- |
| P0 | Checkout/runtime comparison, diagnostic reproduction and live model settings confirmed. Historical model response cannot be recovered from collapsed diagnostics. |
| P1 | Wire vocabulary agreed with Membership, base64 transport added, originals visually annotated and file identities matched as recorded below. Identical fixture and producer/consumer tests verified. |
| P2 | Seven new tests failed on original code for precise classification reasons, legacy classification state and missing processing mode. Further bounded-context and transport regressions added. |
| P3 | Four-class diagnostics, template/continuation prompt guidance, legacy pending-context output and one budgeted joint image review implemented. Current/adjacent classifications and relationships remain identity-bound proposals. Membership automatic scheduling still required. |
| P4 | Existing tool accepts manual hints and separate text organization/image re-extraction. Reuses dedicated client and source-bound parser; manual type, supplied content, blank values and precision survive; image crop provenance retained. |
| P5 | 434 focused offline tests pass after physical-guard follow-up; CodeGraph sync and git diff --check pass. Both Dockerfiles include the new module; no image was built. |
| P6 | Not run. No automatic recognition accuracy, deployed behavior or end-to-end UI acceptance claim. |

Final offline command:

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_calculation_processing.py tests/test_pdf2md_calculation_sheet.py tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_upload_semantics.py tests/test_pdf2md_enhanced_table_query.py tests/test_pdf2md_content_quality.py
```

Result before the physical-guard follow-up: **422 passed**, 64 existing warnings. The first seven failure-first tests
are included. New processing coverage includes wrong tenant/document/version/hash,
same/distant/duplicate identities, no image/context, budget exhaustion, manual
constraint, text-only wire messages, precision/blank preservation, invalid
base64, full-PDF hash mismatch, actual client multi-image message ordering,
changed table numbers, forward joint review, error-log redaction and cancellation
propagation. Existing broad regressions cover source/geometry preservation and
ordinary table query guards.

Changed production modules: `calculation_sheet.py`, `calculation_processing.py`,
`single_page_tools.py`, `page_processor.py`, `server.py`, `vlm_client.py`.
The new module is an internal coordinator behind the existing tool, not another
public service. Both Dockerfiles add it; no container operation was performed.
CodeGraph was synced after each batch. No pre-existing dirty source hunk was
overwritten. Old exact-dictionary/stub assertions were updated for the additive
not-run diagnostic and safe-error keyword.

Important limits: crop identity is authorized by Membership; only a full-PDF input
can be locally compared to the complete PDF SHA-256. All model transcriptions
remain image-unverified. Legacy extraction requests pending context; it does not
read Membership or autonomously traverse a document. Synchronous provider calls
already running cannot be forcibly stopped by executor RPC cancellation; the
consumer must retain task/version protection. Logical budgets alone are not
physical HTTP request caps; the new processing guard is recorded below.

## Membership sample identity confirmation

The collaborating Membership task reported the following read-only verification:

- GBT151: tenant `6`, document `eb795308-496e-403d-be95-d2743618186f`, version `1`,
  PDF page `7`, object `p7_t1`, table PK
  `6:eb795308-496e-403d-be95-d2743618186f:1:7:p7_t1`.
  Its retained layout ID is **`p1-o004-table`**, from a source crop; do not rename
  it based on the current PDF page. Stored size `7261025` and MD5
  `c5113f309608ec6616aef557b621b9dc` match the located full original.
- ASME: stored size `2800246` and MD5 `72b051f861ccfa79c3669337970cd4fc` match
  the located full original. The full SHA-256 values are in the P1 annotation
  document. Membership must compute SHA-256 from bytes, never relabel its MD5
  fallback as SHA-256.

These storage checks were performed by the Membership task; this MCP task
independently hashed the local originals and inspected the referenced page images.

## P6 preparation (not executed)

Runtime caps were read without credentials: container timeout cap is 600 seconds,
page timeout is 600 seconds, and unset retry/token cap variables use server
defaults of **0 outer retries** and 16384 output tokens. This differs from the
direct client's default of 2 outer retries. SDK retries and stream/non-stream
fallback are additional physical activity; zero outer retries is not a hard
physical-request cap.

Subsequent read-only Router queries confirmed the live MongoDB binding is
provider **Qwen**, model **`qwen3-vl-flash`**. Provider configuration has timeout
1800 seconds, max_tokens 32768 and context_window 32768, without an explicit
max_retries field. MCP server normalization therefore produces **600 seconds,
16384 max_tokens and 0 outer retries**. The running container's installed SDK
reports `DEFAULT_MAX_RETRIES=2`, and client construction does not override it.
Router injection does not supply table_analysis_max_model_calls; its default
logical budget is 2. This read performed no model call and printed no key, token
or service address. The findings were sent to the Membership task.

The next acceptance uses approved test copies of the two hash-matched originals,
retaining the original reviewed documents. Use the nine annotated table objects
(ASME 11, 12 upper/lower, 13 upper/lower; GBT151 7, 8, 9 upper/lower) for automatic
first pass and one independent repeat. Check type, relation and current-object
content against the images. Separately exercise organize-existing and reextract
on one calculation object per document, plus Membership pure manual edits and
reopening published test copies. A manual fix cannot turn an automatic failure
into a pass.

Proposed logical budget: 2 per automatic object (at most 36 for the two passes),
1 per organization and 2 per re-extraction (at most 6 more), hence **42 logical
calls total**. Stop on exhaustion; no extra repair passes. Fix the model and
timeout/output-token settings before requesting live-call authorization. A
physical-request guard with SDK retries disabled has now been implemented for
the new processing entry (below). No live probe was run.

The MCP service build context is `mcp/servers/PDF2MDEnhanced` in
`docker-compose.mcp-servers.yml`. Per AGENTS.md, the agent does not build/start/
restart containers. Once runtime rollout is explicitly approved, the user can
run from the repository root (commands shown for review, not executed):

```sh
docker compose -f docker-compose.mcp-servers.yml --profile optional build pdf2md-enhanced-mcp
docker compose -f docker-compose.mcp-servers.yml --profile optional up -d --no-deps pdf2md-enhanced-mcp
```

Membership rollout remains in its task's scope. After both artifacts are updated,
verify the registered signature and source hashes in the actual image, then run
the approved copy-only matrix. P6/M6 remain open until both sides report matching
runtime results and the independent repeat.

## Physical-budget follow-up

Membership requested an executable physical HTTP bound for P6. Three new
failure-first tests initially failed, then passed after adding the processing-only
HTTPX request hook. It runs before every send, including HTTP redirects and
stream/non-stream/token-correction fallback. SDK-wrapped hook exhaustion preserves
the stable `table_analysis_physical_budget_exhausted` reason. SDK and outer
retries are both zero for the new processing client; legacy clients are unchanged.

The per-RPC cap defaults to 2 for organization and 4 for auto/reextract, reduced
when the logical allowance is smaller. An explicit
`vlm_config.table_analysis_max_physical_requests` may lower the cap to zero but
cannot increase it. Response budget fields include actual attempted sends,
the physical cap and SDK retries. Guards do not reset between the current-object
call and its adjacent joint review.

The full focused command now reports **434 passed**, 64 existing warnings. Tests
use the real installed SDK over HTTPX MockTransport; no network/model calls occur.
They cover 503 fallback, provider token-range errors, redirects, repeated logical
calls, SDK retry disabling, zero/invalid caps, and failed MCP envelope retention.

P6 can reserve **42 logical and 84 physical requests in total** for the specified
matrix only if each RPC reserves its full allowance *before* dispatch (image 2/4,
text 1/2). All follow-ups/retries consume new reserved quota; do not refund unused
logical slots and dispatch unlimited fresh requests. The MCP enforces each RPC's
cap; Membership's manifest must enforce the whole-run allocation. This has been
communicated to the Membership task. Runtime deployment and live acceptance are
still pending.
