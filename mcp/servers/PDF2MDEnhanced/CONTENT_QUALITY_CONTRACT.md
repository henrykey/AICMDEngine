# Generic object quality and image transport (additive contract)

## Scope and evidence

Source layout, semantic fields, query projection and image assets are independent.
A successful crop proves bytes from the supplied page rectangle, not correct OCR,
semantic correctness, exhaustive object discovery or correct model geometry.
Existing Markdown/HTML and separate formula LaTeX/number/name fields remain the
source/display contract. No document-specific rules or adjacent-page fetching are
introduced. Runtime adoption requires a separately deployed matching MCP package.

A layout block labelled formula that contains one complete structurally valid
HTML table is classified as a table before layout identity creation. This does
not reconstruct a parent table when OCR returned only separate equations or
omitted the region. Existing targeted crop recovery remains the recovery path;
callers must supply the actual target/evidence, never infer a page-wide repair
from a table-query request. A changed classification requires consumers to use
the returned layout identity, never a previous array position.

## Parent and cell association

Layout-driven upload output formulas and figures have `parent_relation`:

- `page_no`, `bbox_space=normalized_page`, `status=resolved|unresolved`.
- A uniquely containing table establishes `table_layout_id`.
- A uniquely containing supplied source-cell bbox establishes `cell_source=rNcM`
  (zero-based source origin, including merged cells), with
  `evidence=unique_bbox_containment`.
- No coordinate estimation from row order, nearby labels, repeated formula text
  or another page is allowed. All four bbox coordinates must be finite in [0,1],
  ordered, with the same explicitly declared coordinate space.

Reasons: `unreliable_object_bbox`, `ambiguous_parent_table`,
`missing_cell_geometry`, `ambiguous_parent_cell`, `no_containing_table`.
The last reason is also normal for a standalone formula/figure; keep that object
independent. An unresolved relationship does not erase its source or imply that
its semantic fields failed. Missing cell geometry must not produce a guessed
cell link. Relationship output currently belongs to the layout-driven upload
route, not every legacy single-page response.

## Actual image transport

The layout-driven upload route exports each identified figure through the existing
page-crop helper while the page-owned raster still exists. `image_asset` contains:

- On success: `status=available`, `data` (PNG data URI), `mime_type=image/png`,
  `sha256`, pixel `width/height`, `pixel_bbox`, `bbox_space=pixel_page`,
  `page_no`, and `layout_id`.
- On failure: `status=unresolved`, `page_no`, and a stable reason only:
  `unreliable_image_bbox`, `image_asset_budget_exceeded`, or
  `image_asset_generation_failed`.

Crops have no padding and use outward integer pixel rounding. Each request allows
at most 32 crops, 8 MiB PNG bytes per crop, 16 MiB PNG bytes total, and a source
raster of at most 16 million pixels. Base64 adds about one third to transport size;
consumer/RPC body limits may require a smaller batch. This is not a new public
filesystem-reading tool: the helper receives only the internally resolved page
raster. Provider image URLs and container-private paths are not asset URLs.
Crops live in a request-owned temporary directory and are removed on success or
failure. No files survive just to support a returned URL. Bytes are valid after
the temporary directory is removed; the caller owns subsequent byte retention.
Repeated calls have deterministic crop hashes for the same raster/rectangle.

MCP does not discover an image that the upstream layout never identified. Textual
descriptions do not substitute for original pixels. Missing table-cell geometry
can coexist with an available image and an unresolved parent-cell relation.
Original table HTML is unchanged; no dangling image Markdown is inserted.

## Membership handoff and retry policy

Membership must validate document/tenant/version/revision and page identity,
accept parent objects and relations together, verify bytes/hash/dimensions, save
assets, and replace data URIs with durable asset URLs in a separate derived
rendering representation. Source HTML remains authoritative. Recheck that the
parent and merged source cell still exist before linking. Never persist private
paths, publish unresolved links, or promote diagnostic query candidates.

`description_language_mismatch`, provider failures and asset generation failures
may warrant a caller-controlled retry after reviewing evidence/configuration;
no retry is scheduled here. Missing geometry/context and deterministic source
blockers require new evidence or correction, not blind model retries. Budget
exhaustion requires caller batching. These reasons do not claim that page writeback,
asset persistence, indexing, document scheduling, or six-page budget skipping has
been fixed. Those operations and their statistics remain Membership-owned.


## Explicit missing-parent recovery

`extract_page_tables` accepts `context.structure_target` with `type=table`,
`layout_id`, `bbox`, `bbox_space=normalized_page`, `page_no`, and `source_sha1`
(the hash of the supplied file bytes, matching the normal source payload).
The caller must also supply `content_provider_plan` and `image_provider_plan` as
ordered lists of explicitly allowed model attempts. Content accepts `glm_ocr` and
`vlm_ocr`; image recovery accepts `vlm_ocr`. Missing plans return
`recovery_provider_plan_required` before constructing a provider. Each plan is
bounded by the shared `max_model_calls`; no unlisted provider is attempted.
Optional fields: `request_id`, `max_model_calls` (default 1, integer 0..4),
`source_cells`, and `requires_previous_context`. Input is limited to 200,000 JSON
characters and 2,000 supplied source cells. Validate source hash, page and geometry
before provider construction; a mismatch returns
`structure_target_source_mismatch` and zero calls. Invalid target/budget returns
`invalid_structure_target`/`invalid_model_budget`. This does not replace caller
authorization or current-version checks.

The existing `_recover_layout_objects` and crop helper recover exactly the chosen
rectangle with zero padding; no layout discovery, page scan or adjacent-page fetch
is triggered. The call cap is shared across GLM/VLM attempts. Return `tables`,
`figures`, actual `model_calls`, and `structure_recovery` containing binding,
diagnostics and complete/unresolved. Completion means validated structural payload,
not complete semantic fields or original-image quality acceptance. Continued-table
context may remain in dependencies even after a readable structure is returned.
A zero budget does not construct a provider. Old requests without structure_target
retain their normal extraction route. Query enhancement remains a separate branch.

## Cell-owned image regions

A source cell may carry `image_regions`, each with a nonempty stable `image_id`,
`bbox`, and `bbox_space=normalized_page`. The parent table supplies its layout_id
and the cell supplies its source row/col and reliable normalized bbox. The same
asset pipeline turns these explicit regions into geometry-only figures even when
upstream layout emitted no separate figure. Stable derived identity is
`table_layout_id:rNcM:image:image_id`; repeat calls do not append another object.
No image URL or file path supplied in a region is fetched.

Unique containment must agree with the declared parent and cell. A mismatch gives
`cell_image_geometry_conflict`; unresolved cell-derived geometry blocks cropping,
so an explicit table target cannot export an adjacent region. Missing/invalid
identities and duplicates are returned in `table.image_unresolved` with
`invalid_cell_image_identity`, `invalid_cell_image_regions` or
`image_identity_conflict`. The previously specified count/byte/pixel budgets and
request-owned cleanup apply. Raw table HTML is still unchanged. This capability
uses supplied reliable image/cell regions; automatic recognition quality remains
a real-model acceptance item.


## Formulas embedded in HTML cells

Layout-driven table output and explicit target recovery also expose
`contained_formulas` and `contained_formula_sources`. They reuse the grid/source
validator and existing math delimiter/number parser, operating separately within
each cell. Every formula records `parent_table_layout_id`, `cell_source`, stable
`source_ref` based on cell and character offsets, `source_field=raw_html`,
`start/end`, and exact source `latex`. The matching raw_html is under
`contained_formula_sources[cell_source]`. Only an explicit source label populates
formula_no. Names/descriptions remain missing until independently supplied.
These nested descriptors are not copied to the standalone formulas array and
must not be rendered a second time. Invalid source mappings produce empty
contained_formulas plus `contained_formula_quality.status=unresolved`, not guessed
links. Source HTML and existing independent formulas remain unchanged.

## Calculation sheets

Calculation sheets use a separate type, VLM item-extraction method and source-bound
validator instead of a geometric grid. `table_content_quality` is independent of
semantic descriptions and structural recovery. See CALCULATION_SHEET_CONTRACT.md
for budgets, metadata, downstream guards and remaining image-review requirements.
