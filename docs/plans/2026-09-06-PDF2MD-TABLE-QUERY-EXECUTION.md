# PDF2MD complex-table query enhancement execution report

Date: 2026-09-06. Authorized MCP implementation and offline verification delivered;
real-model semantic acceptance and product/runtime acceptance remain unexecuted.

## Checkout and scope

- AICMDEngine: `/Users/kehongwei/workspace/AICMDEngine`, `main`,
  HEAD `64446cffb5664e76dddf8a327a8a5bba1164a6a8`, initially clean.
- Membership: HEAD `c62b34ec3786efb8006e826dd7945a0c561b4006`, read only.
  Existing untracked plan and `scripts/probe_complex_table_queries.py` preserved.
- No commit, push, real model/provider call, dependency download, image build,
  container start/restart, deployment, Membership edit or business-data mutation.
- CodeGraph status/query recovered successfully; incremental sync passed after
  implementation batches. No full rebuild was performed.

## Changes and reused capabilities

- `server.py`, `single_page_tools.py`: optional `query_enhancement` on the actual
  registered `extract_page_tables` tool; unchanged default path and input table.
- `table_query.py`: reuse `_html_table_to_grid` source cells/status, preserve
  merged origins, layered header bindings, units, conditions, groups and text
  spans; deterministic values and explicit interval boundaries; bounded semantic
  proposals and validation; independent source assertions; fail-closed output.
  Deterministic source assertions, caller conflicts and missing previous context
  now block before provider creation (`model_calls: 0`). `max_model_calls` is an
  upper bound; model use requires explicit `query_strategy=semantic_review` or
  `model_required`.
- `vlm_client.py`: text or explicit object-image interpretation through existing
  transport. Safe error diagnostics enabled for this path, default behavior retained.
  Cross-service crops may use bounded PNG/JPEG data input, materialized only for
  the call and deleted afterward; image presence never changes image-verification
  quality state.
- `Dockerfile`, `Dockerfile.cn`: include the new runtime module in explicit COPY
  manifests. This was a source manifest check, not an image build.
- `tests/test_pdf2md_enhanced_table_query.py`: synthetic offline tests, including
  actual MCP registration → handler → real semantic method → provider wire stub.
- `TABLE_QUERY_CONTRACT.md`: request/response, source references, states, limits,
  reference queries and Membership field mapping. `AGENTS.md` records test command
  as required by its testing instructions.

No pandas/lxml dependency was introduced: three existing-parser grids exactly
match the three saved pandas+lxml baseline grids. Local pandas is available but
lxml is not; this comparison reuses the supplied baseline, not a fresh lxml run.

## Loop results

| Loop | Offline outcome | Limits / unexecuted |
| --- | --- | --- |
| 1 | Checkout, call-chain, identity/hash/revision binding and registration checked. | Membership semantic enhancement uses its own chat repair path; not automatically connected to this MCP change. |
| 2 | Layered headers, merged origins, blank rows/cells, fractions, leading zeroes, duplicate values and bbox lineage covered. | Ambiguous all-td headers require semantic interpretation; no parser replacement. |
| 3 | Provider stubs cover references, token slices, altered values, omissions, identity mismatch, timeout, truncation, language, conditions and bounded retries. | No real provider acceptance. Retry feedback remains within the same target table; no independent region execution engine. |
| 4 | Three PDF hashes/identities verified; all 13 selected assertions have expected/actual/status/source in private report. | Human bindings and independent observations are explicit; not automatic model results or full-table truth. |
| 5 | Registered MCP integration, existing table/formula/figure regressions, compilation, diff checks and runtime COPY manifests pass. | No deployment or cross-service integration acceptance. |

Final regression command:

```sh
.venv/bin/python -m pytest -q --no-cov tests/test_pdf2md_enhanced_table_query.py tests/test_pdf2md_enhanced_single_page_tools.py tests/test_pdf2md_enhanced_object_recovery.py tests/test_pdf2md_enhanced_upload_semantics.py
```

Follow-up table-query result: **68 table-query tests passed**. The affected suite
result is **330 passed** after the image and strategy corrections below. New tests cover pre-call
blockers, explicit model strategy, temporary cross-service image input, real
decodability/MIME/transport checks, and unresolved tilde ranges; 64
pre-existing
environment/deprecation warnings. `python -m py_compile` passed for the four
changed/new Python runtime modules and the new test file. `git diff --check` passed.
`codegraph sync` passed.

Earlier test feedback: an import-path error in the new test and a mismatched
FastMCP test accessor were corrected. A broader selection included the remote
`test_pdf2md_enhanced_mcp.py` script: 300 tests passed and two remote entries failed
setup because `jwt_token` was absent; neither executed a network call. Those
remote entries are excluded from the authorized offline suite and remain untested.
No failing assertion was removed or weakened.

## Private sample evidence

Local files (not added to Git):

- `/tmp/docintel-complex-table-samples-20260906/verify_query_enhancement.py`
- `/tmp/docintel-complex-table-samples-20260906/query-enhancement-offline-report.json`
- `/tmp/docintel-complex-table-samples-20260906/query-grid-comparison.json`

Run the private script with the repository `.venv/bin/python`. It records input
hash, request configuration, contract version, source bindings and individual
case outcomes. All returned table objects equal their original supplied objects.

| Sample | Selected assertion results | Evidence qualification |
| --- | --- | --- |
| GB/T 151 | 5/5 boundary/percentage queries passed. | Header bindings are human supplied through a provider stub; numerical filtering is actual deterministic code. |
| GB/T 150 | 4/4 correctly blocked by content conflict. | Independent image observation identifies the next serial position as 12 while HTML inherits 11; no corrected table is emitted. Automatic image conflict discovery is untested. |
| ASME | 3/3 D-region candidate source/condition checks passed; missing preceding context correctly blocked. | Human spans in D remain available only as quarantined diagnostics; notes/continuation keep whole-table lookup unavailable. |

The first private check exposed fullwidth comparison syntax and an incorrectly
chosen observation coordinate. The parser now supports general fullwidth
comparisons with a synthetic regression; the private observation was corrected
to the actual misaligned serial position. Original HTML and expected cases were
never rewritten.

## Remaining acceptance and consumption limits

1. Real model interpretation and crop-to-source conflict detection are untested.
   Source binding checks cannot prove the model chose the correct semantic relation.
2. Current Membership drops detailed conditions/source mappings and labels any
   nonempty sections complete. Partial candidates therefore are not exposed as
   consumable sections. Future integration must preserve the new semantics and
   add the gate before using existing persistence/index lifecycle.
3. `complete` means projection validation against supplied sources, not image
   truth, whole-product completion, or deployment. Content consistency separately
   states `source_bound_not_image_verified` or `conflict`.
4. Arbitrary interval expressions, ambiguous tilde boundaries, interpolation and
   cross-table evaluation remain unsupported and cannot be silently executed.
5. Original uploads and deployed containers remain unchanged. Product acceptance
   requires separately authorized real MCP calls and Membership integration.

## Follow-up verification

- The sample manifest and all three sample directories/files were readable;
  originals and expected answers under `/tmp/docintel-complex-table-samples-20260906/`
  were not modified.
- Mock/provider-stub tests verify only the image-conflict response contract.
  Real-model cases still requiring authorized execution are the GB/T 150
  serial/source mismatch, ASME continuation/curve association, and GB/T 151
  header/grade association. Expected results are source-scoped `content_conflict`
  or unresolved semantic binding while preserving the original table.
- The unchanged private verification script now reports ambiguous ASME/GB/T 151
  cases as blocked because it does not set the new explicit `query_strategy`; this
  is the intended zero-call default. Callers requiring provider/model interpretation
  must add `query_strategy=semantic_review`.
- Truncated headers, MIME mismatches, undecodable images and pixel-over-limit
  inputs are rejected before provider creation with `model_calls: 0`. JPEG input
  is sent as `data:image/jpeg` with the exact validated bytes; PNG remains
  `data:image/png`.

## Initialization cleanup and legacy image-format follow-up

Starting HEAD remained `64446cffb5664e76dddf8a327a8a5bba1164a6a8` on `main`.
The five uncommitted files from the previous rounds were preserved. No Membership,
sample or runtime inspection/mutation was performed in this follow-up.

The new offline regressions first returned **8 failed, 5 passed**:
two owned-image cases leaked files when the factory raised or the real client
failed to parse `max_tokens`; two caller-owned cases exposed unsafe/non-specific
initialization error handling; WebP/BMP/TIF/TIFF failed before reaching the wire.
PNG/JPEG and the retry cleanup controls passed. After the minimal fix all **13
new cases passed**.

- Provider creation now executes inside the crop owner's `try/finally`.
  Factory exceptions and real client configuration errors return
  `model_initialization_failed`, zero model calls, and the unchanged table.
  Tests check removal of owned files and byte preservation of caller-owned files.
  Retry tests cover call failure then success, truncation then success, and
  exhausted failures; all paths remove the owned crop.
- Shared image sending preserves PNG/JPEG bytes/MIME and sends WebP with
  `image/webp`. BMP/TIFF use existing PyMuPDF decoding and PNG encoding in memory.
  The default single-page tool tests run through actual context preparation,
  structured extraction and shared image sending, stubbing only client setup and
  the provider wire. They decode outgoing bytes, check dimensions/pixels and MIME,
  assert unchanged input files, and verify the tool's work directory is removed.
  No conversion files or new runtime dependencies are introduced.

This evidence is offline implementation/transport-contract verification. Real
provider support, automatic source-image error detection, the running image and
Membership integration remain unverified. Ambiguous tilde ranges remain blocked;
human assertions and stub responses do not prove real-model semantic correctness.

Final affected-suite run (command above): **343 passed, 64 warnings** (75 query
contracts, 110 single-page contracts, 74 object-recovery contracts, 84 upload
semantic contracts). Compilation of the two changed runtime modules and both
test modules passed; `git diff --check` passed. The two synthetic temporary crops
left by the deliberately failing pre-fix tests were removed by exact path.
No commits, pushes, builds, restarts, deployments or external model calls occurred.
