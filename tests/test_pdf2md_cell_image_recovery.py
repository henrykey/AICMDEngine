import base64
import copy
import importlib

import fitz
import pytest
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools as sp
from tests.test_pdf2md_enhanced_bad_text_policy import LayoutLedgerGLMOcrClient, LayoutLedgerVLMClient, _layout_raw

pp = importlib.import_module(sp.__package__ + '.page_processor')
HTML = '<table><tr><td>Original 001</td></tr></table>'


def geometry(block):
    return {'layout_id': block['layout_id'], 'type': 'table', 'complete': True,
            'status': 'EXTRACTED', 'contains_images': True,
            'source_cells': [{'row': 0, 'col': 0, 'rowspan': 1, 'colspan': 1,
                'bbox': [0, 0, 1, 1], 'bbox_space': 'normalized_crop',
                'image_regions': [{'image_id': 'a', 'bbox': [.25, .25, .75, .75],
                                   'bbox_space': 'normalized_crop'}]}]}


def process_explicitly(source_path, page_no, policy, vlm_config, routing_config, prev_context):
    first = pp.process_page(source_path, page_no, policy, vlm_config,
                            {**routing_config, 'docs_recovery_phase': 'recognize'}, prev_context)
    assert first['decision']['glm_calls'] + first['decision']['vlm_calls'] >= 1
    import json
    json.dumps(first['_docs_raw_layout'])
    layout = first.get('layout', [])
    elements = first['rag']['elements']
    ids = list(dict.fromkeys([item['layout_id'] for item in layout if item.get('type') == 'table']
                             + [item['layout_id'] for item in elements.get('tables', []) if item.get('layout_id')]))
    figs = [item['layout_id'] for item in elements.get('figures', []) if item.get('layout_id')]
    request = {'tables': ids, 'table_images': ids, 'figures': figs, 'visual_types': figs,
               'table_provider_plan': ['glm_ocr', 'vlm_ocr', 'vlm_ocr'],
               'image_provider_plan': ['vlm_ocr', 'vlm_ocr'],
               'visual_provider_plan': ['vlm_ocr', 'vlm_ocr'],
               'table_model_budget': 3 * len(ids), 'image_model_budget': 2 * len(ids),
               'visual_model_budget': 2 * len(figs)}
    return pp.process_page(source_path, page_no, policy, vlm_config,
                           {**routing_config, 'docs_recovery_phase': 'recover',
                            '__docs_saved_layout': first['_docs_raw_layout'],
                            'docs_recovery_selection': request}, prev_context)


@pytest.mark.parametrize("layout_enabled", [True, False])
@pytest.mark.parametrize("figure_semantics", [True, False])
def test_conversion_preserves_complete_table_and_inspects_cell_images(tmp_path, monkeypatch, layout_enabled, figure_semantics):
    path = tmp_path / 'page.pdf'
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    # Two complete drawings lie strictly inside the two returned image regions.
    for bounds in [(30, 40, 40, 60), (60, 40, 70, 60)]:
        page.draw_rect(fitz.Rect(*bounds), color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(path)
    doc.close()
    class OCR(LayoutLedgerGLMOcrClient):
        raw = _layout_raw([{'label': 'table', 'bbox_2d': [20, 20, 80, 80], 'content': HTML}], HTML)
        def extract_page(self, path):
            return sp.OcrResult(markdown=HTML, tables=[sp.OcrElement(kind='table', source='glm_ocr', markdown=HTML,
                raw={'bbox': [.2,.2,.8,.8], 'bbox_space': 'normalized_page'})])
    calls = []
    class VLM(LayoutLedgerVLMClient):
        def extract_region_structured(self, path, semantic_objects=None):
            return {'tables': [{'object_ref': 'tables:0', 'title': 'Types',
                'description': 'Equipment structures.', 'contains_images': True,
                'image_unresolved': [{'reason': 'missing_cell_image_geometry'}]}]}
        def extract_object_structured(self, path, block, compact=False):
            calls.append(block)
            self.last_object_call_info = {'json_status': 'object', 'finish_reason': 'stop'}
            if block["type"] == "figure":
                return {"layout_id": block["layout_id"], "type": "figure", "status": "EXTRACTED",
                        "complete": True, "description": "A red rectangular component occupies the center of the diagram."}
            result = geometry(block)
            result['source_cells'][0]['image_regions'] = [
                {'image_id': 'left', 'bbox': [.1, .2, .4, .8], 'bbox_space': 'normalized_crop'},
                {'image_id': 'right', 'bbox': [.6, .2, .9, .8], 'bbox_space': 'normalized_crop'},
            ]
            return result
    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', OCR)
    monkeypatch.setattr(pp, 'DynamicVLMClient', VLM)
    result = process_explicitly(str(path), 1, 'auto', {'provider': 'fixture'},
        {'source_page_no': 7, 'render_dpi': 150, 'render_cleanup_with_llm': False,
         'layout_ledger_enabled': layout_enabled, 'figure_semantic_description_required': figure_semantics,
         'ocr_config': {'glm_ocr': {'enabled': True}}}, None)
    assert len(calls) == 1
    assert calls[0]["recovery_target"] == "cell_images"
    table = result['elements']['tables'][0]
    assert table['markdown'] == HTML
    assert table['bbox'] == [.2, .2, .8, .8]
    assert table['bbox_space'] == 'normalized_page'
    assert len(result["elements"]["figures"]) == 2
    assert all(f['image_asset']['status'] == 'available' for f in result['elements']['figures'])
    assert table['cell_image_inspection_status'] == 'complete'
    if layout_enabled:
        assert result['reconciliation']['complete']
        assert not result['reconciliation']['unmatched_payload_layout_ids']


@pytest.fixture
def source_image(tmp_path):
    path = tmp_path / 'source.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 100), False)
    pix.clear_with(255)
    pix.save(str(path))
    from PIL import Image, ImageDraw
    with Image.open(path) as image:
        draw = ImageDraw.Draw(image)
        for x, y in [(76, 37), (76, 63), (124, 63), (100, 50), (55, 27)]:
            draw.rectangle((x, y, x + 1, y + 1), fill="black")
        image.save(path)
    return path


def table_target():
    return {'layout_id': 'p3-table', 'bbox': [.2, .2, .8, .8], 'bbox_space': 'normalized_page',
            'markdown': HTML, 'contains_images': True, 'manualReviewRequired': True,
            'image_unresolved': [{'reason': 'missing_cell_image_geometry'}]}


def test_content_recovery_survives_failed_image_localization(source_image, tmp_path):
    raw = _layout_raw([{'label': 'table', 'bbox_2d': [20, 20, 80, 80],
                       'content': '<table><tr><td>incomplete'}])
    outcome = pp.build_layout_outcome(raw, 7, 100, 100)
    target = {**pp.recovery_blocks(outcome)[0], 'recovery_target': 'table_content_with_cell_images'}

    class OCR:
        enabled = True
        use_layout_parsing = True
        def extract_table_html(self, path):
            return '<table><tr><td>incomplete'

    class VLM(GeometryClient):
        def extract_table_html(self, path, block, compact=False):
            self.calls.append(('content', compact))
            return HTML
        def extract_object_structured(self, path, block, compact=False):
            self.calls.append((block.get('recovery_target'), compact))
            self.last_target = block
            self.last_object_call_info = {'json_status': 'object', 'finish_reason': 'stop'}
            return {'layout_id': block['layout_id'], 'type': 'table', 'complete': False}

    client = VLM()
    counts = pp._recover_layout_objects(source_image, tmp_path, outcome, [target], client, True,
                                       1, 0, glm=OCR(), max_model_calls=3)
    assert counts[:2] == (1, 2)
    assert client.calls == [('content', False), ('cell_images', False)]
    assert client.last_target['source_cell_origins'] == [{'row': 0, 'col': 0, 'rowspan': 1, 'colspan': 1}]
    assert len(outcome['payloads']['tables']) == 1
    table = outcome['payloads']['tables'][0]
    assert table['markdown'] == HTML
    assert table['image_unresolved']
    assert table['manualReviewRequired'] is True
    assert not table.get('source_cells')


class GeometryClient:
    enabled = True
    def __init__(self, responses=None):
        self.responses = iter(responses) if responses is not None else None
        self.calls = []
        self.targets = []
        self.last_object_call_info = {}
    def extract_object_structured(self, path, block, compact=False):
        self.calls.append((fitz.Pixmap(path).width, compact))
        self.targets.append(copy.deepcopy(block))
        self.last_object_call_info = {'json_status': 'object', 'finish_reason': 'stop'}
        response = next(self.responses) if self.responses is not None else geometry(block)
        if isinstance(response, Exception):
            raise response
        return response


def run_recovery(source_image, tmp_path, table=None, client=None, **kwargs):
    table = table if table is not None else table_target()
    client = client or GeometryClient()
    payload = {'tables': [table], 'figures': []}
    counts = pp._recover_missing_table_images(source_image, tmp_path, payload, client, True, 1, **kwargs)
    return table, client, counts


def test_localization_copies_parsed_source_spans(source_image, tmp_path):
    table = {**table_target(), 'markdown': '<table><tr><th>A</th><th>B</th></tr>'
             '<tr><td rowspan="2">[image]</td><td>x</td></tr><tr><td>y</td></tr></table>'}
    response = geometry(table)
    response['source_cells'][0].update(row=1, rowspan=2)
    table, client, counts = run_recovery(source_image, tmp_path, table, GeometryClient([response]))
    origins = client.targets[0]['source_cell_origins']
    assert {'row': 1, 'col': 0, 'rowspan': 2, 'colspan': 1, 'image_placeholder': True} in origins
    assert counts[1] == 1
    assert table['source_cells'][0]['rowspan'] == 2
    assert not table['image_unresolved']
    assert 'source_cell_origins' not in table


def test_source_parse_failure_preserves_table_without_model_send(source_image, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError('invalid_table_source')
    monkeypatch.setattr(sp, '_normalize_table_contract', fail)
    table, client, counts = run_recovery(source_image, tmp_path)
    assert table['markdown'] == HTML
    assert table['image_unresolved']
    assert client.calls == []
    assert counts[1] == 0


def test_wrong_source_cell_identity_is_retried_with_specific_error(source_image, tmp_path):
    wrong = geometry(table_target())
    wrong['source_cells'][0]['row'] = 99
    table, client, counts = run_recovery(source_image, tmp_path,
                                        client=GeometryClient([wrong, geometry(table_target())]))
    assert counts[1] == 2
    assert client.targets[1]['recovery_error'] == 'cell_source_mismatch'
    assert not table['image_unresolved']


def test_padded_crop_supplies_authoritative_table_boundary(source_image, tmp_path):
    table = table_target()
    client = GeometryClient()
    pp._recover_layout_objects(source_image, tmp_path, {'payloads': {'tables': [table]}},
        [{**table, 'type': 'table', 'recovery_target': 'cell_images'}], client, True, 1, .02)
    x0, y0, x1, y1 = client.targets[0]['table_bbox_in_crop']
    assert 0 < x0 < x1 < 1
    assert 0 < y0 < y1 < 1
    assert 'table_bbox_in_crop' not in table


def test_geometry_diagnostics_omit_source_text_and_generated_ids(source_image, tmp_path):
    import json
    response = geometry(table_target())
    response['source_cells'][0]['text'] = 'PRIVATE_CELL_TEXT'
    response['source_cells'][0]['image_regions'][0]['image_id'] = 'PRIVATE_MODEL_ID'
    _, _, counts = run_recovery(source_image, tmp_path, client=GeometryClient([response]))
    diagnostics = json.dumps(counts[2])
    assert 'PRIVATE' not in diagnostics
    attempt = counts[2]['objects'][0]['attempts'][0]
    assert attempt['cell_geometry'][0]['regions'][0]['bbox_space'] == 'normalized_crop'


@pytest.mark.parametrize('dpi', [150, 300])
def test_projection_uses_original_pixel_rectangle_even_after_resize(source_image, tmp_path, dpi):
    table, client, counts = run_recovery(source_image, tmp_path, source_dpi=dpi)
    assert counts[1] == 1
    assert table['source_cells'][0]['image_regions'][0]['bbox'] == pytest.approx([.35, .35, .65, .65])
    assert table['markdown'] == HTML
    assert table['manualReviewRequired'] is False
    assert not table['image_unresolved']
    _, _, again = run_recovery(source_image, tmp_path, table, client)
    assert again[1] == 0


def test_geometry_retry_preserves_resolution_and_is_bounded(source_image, tmp_path):
    invalid = {'complete': False, 'type': 'table', 'layout_id': 'p3-table'}
    table, client, counts = run_recovery(source_image, tmp_path, client=GeometryClient([invalid, geometry(table_target())]))
    assert counts[1] == 2
    assert client.calls[1][0] == client.calls[0][0]
    assert table['source_cells'][0]['image_regions'][0]['bbox'] == pytest.approx([.35, .35, .65, .65])


@pytest.mark.parametrize('changes', [
    {'layout_id': 'foreign'}, {'type': 'figure'}, {'complete': False},
    {'source_cells': []}, {'contains_images': False},
])
def test_invalid_response_preserves_original(source_image, tmp_path, changes):
    candidate = {**geometry(table_target()), **changes}
    table, client, counts = run_recovery(source_image, tmp_path, client=GeometryClient([candidate, candidate]))
    assert table['markdown'] == HTML
    assert table['manualReviewRequired'] is True
    assert table['image_unresolved']
    assert not table.get('source_cells')
    assert counts[1] <= 2


@pytest.mark.parametrize('space,bbox', [('normalized_page', [.1,.1,.8,.8]), ('normalized_crop', [-.1,0,1,1]), ('normalized_crop', [0,0,float('nan'),1])])
def test_invalid_crop_coordinates_rejected(source_image, tmp_path, space, bbox):
    candidate = geometry(table_target())
    candidate['source_cells'][0]['image_regions'][0].update(bbox_space=space, bbox=bbox)
    table, _, _ = run_recovery(source_image, tmp_path, client=GeometryClient([candidate, candidate]))
    assert not table.get('source_cells')
    assert table['image_unresolved']


def test_shared_budget_not_reset_for_second_phase(source_image, tmp_path):
    history = {'pending': 1, 'attempted': 1, 'objects': [{'layout_id': 'p3-table', 'attempts': [{}] * 4}]}
    table, client, counts = run_recovery(source_image, tmp_path, previous=history)
    assert client.calls == []
    assert any(i['reason'] == 'model_budget_exhausted' for i in table['image_unresolved'])


def test_same_object_can_use_remaining_budget(source_image, tmp_path):
    history = {'pending': 1, 'attempted': 1, 'objects': [{'layout_id': 'p3-table', 'attempts': [{}]}]}
    table, client, counts = run_recovery(source_image, tmp_path, previous=history, max_model_calls=1)
    assert len(client.calls) == 1
    assert not table['image_unresolved']


def test_plain_table_no_extra_call(source_image, tmp_path):
    table = {**table_target(), 'contains_images': False, 'image_unresolved': [],
             'cell_image_inspection_status': 'complete'}
    _, client, counts = run_recovery(source_image, tmp_path, table)
    assert client.calls == []


def test_crop_budget_error_does_not_repeat_recognition(source_image, tmp_path):
    table, _, _ = run_recovery(source_image, tmp_path)
    table['image_unresolved'] = [{'reason': 'image_asset_budget_exceeded'}]
    _, client, counts = run_recovery(source_image, tmp_path, table)
    assert client.calls == []


def test_success_preserves_unrelated_review_state(source_image, tmp_path):
    table = table_target()
    table['warnings'] = ['table_structure_needs_review']
    table, _, _ = run_recovery(source_image, tmp_path, table)
    assert not table['image_unresolved']
    assert table['manualReviewRequired'] is True


def test_direct_entry_recovery_updates_counts(source_image):
    ctx = sp.SinglePageContext(source_path=source_image, image_path=source_image, input_type='image', page_no=3, page_text='')
    calls = {'glm_ocr': 1, 'vlm_ocr': 1}
    tables, figures = [table_target()], []
    sp._attach_single_page_figure_assets(ctx, figures, tables, GeometryClient(), calls, 1,
        {'provider_plan': ['vlm_ocr', 'vlm_ocr'], 'max_model_calls': 2})
    assert calls == {'glm_ocr': 1, 'vlm_ocr': 2}
    assert figures[0]['image_asset']['status'] == 'available'


@pytest.mark.parametrize('change', [{'row': 8}, {'col': 8}, {'rowspan': 2}, {'colspan': 2}])
def test_source_cell_must_match_original_table(source_image, tmp_path, change):
    candidate = geometry(table_target())
    candidate['source_cells'][0].update(change)
    table, client, counts = run_recovery(source_image, tmp_path, client=GeometryClient([candidate, candidate]))
    assert counts[1] == 2
    assert not table.get('source_cells')
    assert any(issue['reason'] == 'cell_source_mismatch' for issue in table['image_unresolved'])


def test_multi_cell_and_merged_cell_images(source_image, tmp_path):
    table = table_target()
    table['markdown'] = '<table><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>'
    candidate = geometry(table)
    candidate['source_cells'] = [
        {'row': 0, 'col': 0, 'rowspan': 2, 'colspan': 1, 'bbox': [0,0,.5,1], 'bbox_space': 'normalized_crop',
         'image_regions': [{'image_id': 'a', 'bbox': [.1,.1,.4,.4], 'bbox_space': 'normalized_crop'},
                           {'image_id': 'b', 'bbox': [.1,.6,.4,.9], 'bbox_space': 'normalized_crop'}]},
        {'row': 1, 'col': 1, 'rowspan': 1, 'colspan': 1, 'bbox': [.5,.5,1,1], 'bbox_space': 'normalized_crop',
         'image_regions': [{'image_id': 'c', 'bbox': [.6,.6,.9,.9], 'bbox_space': 'normalized_crop'}]}]
    table, client, _ = run_recovery(source_image, tmp_path, table, GeometryClient([candidate]))
    assert not table['image_unresolved']
    payload = {'tables': [table], 'figures': []}
    pp._attach_figure_assets(source_image, payload, 3)
    assert len(payload['figures']) == 3
    assert {f['parent_relation']['cell_source'] for f in payload['figures']} == {'r0c0', 'r1c1'}
    assert all(f['image_asset']['status'] == 'available' for f in payload['figures'])


def test_uncertain_presence_is_not_plain_table(source_image, tmp_path):
    table = {**table_target(), 'contains_images': None, 'image_unresolved': []}
    table, client, _ = run_recovery(source_image, tmp_path, table)
    assert len(client.calls) == 1
    assert table['contains_images'] is True


def test_incomplete_table_is_inspected_without_prior_image_marker(source_image, tmp_path):
    table = {**table_target(), 'contains_images': False, 'image_unresolved': [],
             'source_cells': [], 'recovery_quality': 'partial'}
    recovered, client, counts = run_recovery(source_image, tmp_path, table, GeometryClient([geometry(table)]))
    assert counts[1] == 1
    assert recovered['contains_images'] is True
    assert recovered['source_cells'][0]['image_regions']
    assert client.calls == [(120, False)]


def test_ocr_element_structure_quality_survives_to_table_metadata():
    element = sp.OcrElement(kind='table', source='ocr', markdown=HTML,
        raw={'structure_status': 'partial', 'recovery_quality': 'degraded'})
    payload = pp._ocr_element_payload(element, 'table')
    normalized = pp._normalize_structured({'tables': [payload]})
    assert pp._table_needs_cell_image_inspection(normalized['table_metadata'][HTML])


def test_ocr_table_incompleteness_survives_normalization_for_cell_image_inspection():
    normalized = pp._normalize_structured({'tables': [{
        'markdown': HTML, 'structure_status': 'partial', 'recovery_quality': 'degraded',
        'degraded': True, 'warnings': ['table_content_incomplete'],
    }]})
    table = normalized['table_metadata'][HTML]
    assert pp._table_needs_cell_image_inspection(table)


def test_visually_checked_complete_table_is_not_inspected_again():
    table = {**table_target(), 'contains_images': False, 'image_unresolved': [],
             'source_cells': [], 'recovery_quality': 'complete', 'structure_status': 'parsed',
             'cell_image_inspection_status': 'complete'}
    assert pp._table_needs_cell_image_inspection(table) is False


def test_non_layout_incomplete_ocr_table_runs_cell_image_recovery(tmp_path, monkeypatch):
    path = tmp_path / 'page.pdf'
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(fitz.Rect(20, 20, 80, 80), color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(path)
    doc.close()

    ocr_calls = []
    class OCR(LayoutLedgerGLMOcrClient):
        def extract_page(self, source):
            ocr_calls.append(source)
            return sp.OcrResult(markdown=HTML, tables=[sp.OcrElement(
                kind='table', source='glm_ocr', markdown=HTML,
                raw={'bbox': [.2,.2,.8,.8], 'bbox_space': 'normalized_page',
                     'structure_status': 'partial', 'recovery_quality': 'degraded'})])

    calls = []
    def recover(image_path, output_dir, payloads, vlm, enabled, max_objects, **kwargs):
        calls.append((payloads, enabled))
        payloads['tables'][0].update(contains_images=True, source_cell_row_offset=1, source_cells=[{
            'row': 0, 'col': 0, 'rowspan': 1, 'colspan': 1, 'confidence': .99,
            'bbox': [.2, .2, .8, .8], 'bbox_space': 'normalized_page',
            'image_regions': [{'image_id': 'diagram', 'bbox': [.3, .3, .5, .5],
                               'bbox_space': 'normalized_page'}],
        }])
        return 0, 1, {'objects': [{'layout_id': payloads['tables'][0]['layout_id'],
                                   'outcome': 'failed', 'attempts': [{'provider': 'vlm_ocr', 'reason': 'response_json_invalid'}]}]}

    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', OCR)
    monkeypatch.setattr(pp, 'DynamicVLMClient', LayoutLedgerVLMClient)
    monkeypatch.setattr(pp, '_recover_missing_table_images', recover)
    result = process_explicitly(str(path), 1, 'auto', {'provider': 'fixture'},
        {'source_page_no': 7, 'render_dpi': 150, 'render_cleanup_with_llm': False,
         'layout_ledger_enabled': False, 'ocr_config': {'glm_ocr': {'enabled': True}}}, None)

    assert result['cell_image_recovery']['objects'][0]['attempts'][0]['reason'] == 'response_json_invalid'
    assert len(ocr_calls) == 1
    assert len(calls) == 1
    assert calls[0][0]['tables'][0]['recovery_quality'] == 'degraded'
    figure = result['rag']['elements']['figures'][0]
    assert figure['source'] == 'source_cell_image_region'
    assert figure['cell_image_source']['cell_source'] == 'r0c0'
    assert figure['image_asset']['status'] == 'available'


def test_targeted_detection_confirms_table_has_no_cell_images(source_image, tmp_path):
    candidate = {'layout_id': 'p3-table', 'type': 'table', 'status': 'EXTRACTED',
                 'complete': True, 'contains_images': False, 'source_cells': [], 'image_unresolved': []}
    table, _, counts = run_recovery(source_image, tmp_path, client=GeometryClient([candidate]))
    assert counts[1] == 1
    assert table['contains_images'] is False
    assert not table['image_unresolved']
    assert table['manualReviewRequired'] is False


def test_missing_provider_is_explicit(source_image, tmp_path):
    table = table_target()
    payload = {'tables': [table], 'figures': []}
    client = GeometryClient()
    counts = pp._recover_missing_table_images(source_image, tmp_path, payload, client, False, 1)
    assert counts[:2] == (0, 0)
    assert client.calls == []
    assert any(issue['reason'] == 'provider_unavailable' for issue in table['image_unresolved'])


def test_legacy_automatic_table_image_plan_is_rejected(source_image, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("legacy plan must not start OCR or a provider")
    monkeypatch.setattr(sp, 'DynamicVLMClient', unexpected)
    with pytest.raises(ValueError, match='table_image_recovery_replaced_by_table_image_target'):
        sp.extract_page_tables_direct(file_path=str(source_image), input_type='image',
            context={'table_image_recovery': {'provider_plan': ['vlm_ocr'], 'max_model_calls': 1}})


def test_structure_target_rejects_multiple_model_steps(source_image, tmp_path, monkeypatch):
    import hashlib
    def unexpected(*args, **kwargs):
        raise AssertionError("multiple steps must be decided by the caller")
    monkeypatch.setattr(sp, 'DynamicVLMClient', unexpected)
    ctx = sp.SinglePageContext(source_path=source_image, image_path=source_image, input_type='image', page_no=1, page_text='')
    target = {**table_target(), 'type': 'table', 'page_no': 1,
              'source_sha1': hashlib.sha1(source_image.read_bytes()).hexdigest(), 'max_model_calls': 2,
              'content_provider_plan': ['vlm_ocr'], 'image_provider_plan': ['vlm_ocr']}
    out = sp._recover_structure_target('extract_page_tables', 'tables', ctx, target, 'en', {}, {}, tmp_path)
    assert out['structure_recovery']['reason'] == 'invalid_recovery_provider_plan'
    assert out['model_calls'] == {'glm_ocr': 0, 'vlm_ocr': 0}


def test_structure_target_then_selected_image_each_use_one_call(source_image, tmp_path, monkeypatch):
    import hashlib
    class VLM(GeometryClient):
        def __init__(self, cfg):
            super().__init__()
        def extract_table_html(self, path, block, compact=False):
            self.last_object_call_info = {'json_status': 'html', 'finish_reason': 'stop'}
            return HTML
    monkeypatch.setattr(sp, 'DynamicVLMClient', VLM)
    ctx = sp.SinglePageContext(source_path=source_image, image_path=source_image, input_type='image', page_no=1, page_text='')
    source_hash = hashlib.sha1(source_image.read_bytes()).hexdigest()
    target = {**table_target(), 'type': 'table', 'page_no': 1,
              'source_sha1': source_hash, 'max_model_calls': 1,
              'content_provider_plan': ['vlm_ocr'], 'image_provider_plan': []}
    out = sp._recover_structure_target('extract_page_tables', 'tables', ctx, target, 'en', {}, {}, tmp_path)
    assert out['model_calls'] == {'glm_ocr': 0, 'vlm_ocr': 1}
    assert out['figures'] == []
    image_target = {'table': out['tables'][0], 'page_no': 1, 'source_sha1': source_hash, 'provider': 'vlm_ocr'}
    recovered = sp._recover_single_table_image('extract_page_tables', ctx, image_target, 'en', {}, {}, tmp_path)
    assert recovered['model_calls'] == {'glm_ocr': 0, 'vlm_ocr': 1}
    assert recovered['figures'][0]['image_asset']['status'] == 'available'


def test_partial_failure_preserves_existing_asset_evidence(source_image, tmp_path):
    table, _, _ = run_recovery(source_image, tmp_path)
    old_cells = copy.deepcopy(table['source_cells'])
    table['image_unresolved'] = [{'reason': 'missing_cell_image_geometry'}]
    response = {**geometry(table), 'layout_id': 'foreign'}
    table, _, _ = run_recovery(source_image, tmp_path, table, GeometryClient([response]))
    assert table['source_cells'] == old_cells
    assert table['manualReviewRequired'] is True
    payload = {'tables': [table], 'figures': []}
    pp._attach_figure_assets(source_image, payload, 3)
    assert payload['figures'][0]['image_asset']['status'] == 'available'


def test_partial_recovery_adds_image_without_replacing_existing(source_image, tmp_path):
    table, _, _ = run_recovery(source_image, tmp_path)
    old_image = copy.deepcopy(table['source_cells'][0]['image_regions'][0])
    table['image_unresolved'] = [{'reason': 'missing_cell_image_geometry'}]
    response = geometry(table)
    response['source_cells'][0]['image_regions'] = [{'image_id': 'b', 'bbox': [.1,.1,.2,.2], 'bbox_space': 'normalized_crop'}]
    table, _, _ = run_recovery(source_image, tmp_path, table, GeometryClient([response]))
    assert table['source_cells'][0]['image_regions'][0] == old_image
    assert len(table['source_cells'][0]['image_regions']) == 2
    assert not table['image_unresolved']


def test_confirmed_no_images_is_retained_and_not_called_again(source_image, tmp_path):
    table = {**table_target(), 'contains_images': False, 'image_unresolved': []}
    client = GeometryClient([{'layout_id': table['layout_id'], 'type': 'table',
                             'status': 'EXTRACTED', 'complete': True, 'contains_images': False, 'source_cells': []}])
    table, _, _ = run_recovery(source_image, tmp_path, table, client)
    assert table['cell_image_inspection_status'] == 'complete'
    assert table['markdown'] == HTML
    assert not table['image_unresolved']
    run_recovery(source_image, tmp_path, table, client)
    assert len(client.calls) == 1


def test_cut_image_boundary_retries_without_discarding_table(source_image, tmp_path):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (200, 100), 'white')
    ImageDraw.Draw(image).rectangle((75, 25, 125, 75), fill='black')
    image.save(source_image)
    target = table_target()
    # Crop is [40,20,160,80]; first region cuts through the component at y=35.
    clipped = geometry(target)
    corrected = geometry(target)
    corrected['source_cells'][0]['image_regions'][0]['bbox'] = [.2, .02, .8, .98]
    client = GeometryClient([clipped, corrected])
    table, _, _ = run_recovery(source_image, tmp_path, target, client)
    assert len(client.calls) == 2
    assert client.targets[1]['recovery_error'] == 'cell_image_boundary_intersects_content'
    assert table['cell_image_inspection_status'] == 'complete'
    assert table['markdown'] == HTML


def test_cut_image_boundary_exhaustion_stays_reviewable(source_image, tmp_path):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (200, 100), 'white')
    ImageDraw.Draw(image).rectangle((75, 25, 125, 75), fill='black')
    image.save(source_image)
    target = table_target()
    table, client, _ = run_recovery(source_image, tmp_path, target,
        GeometryClient([geometry(target), geometry(target)]))
    assert len(client.calls) == 2
    assert table.get('cell_image_inspection_status') != 'complete'
    assert table['image_unresolved'][-1]['reason'] == 'cell_image_boundary_intersects_content'
    assert table['markdown'] == HTML


def test_math_invalid_complete_table_uses_existing_recovery(source_image, tmp_path):
    broken = '<table><tr><td>coefficient $x_{i</td></tr></table>'
    fixed = '<table><tr><td>coefficient $x_{i}$</td></tr></table>'
    outcome = pp.build_layout_outcome(_layout_raw([
        {'label': 'table', 'bbox_2d': [20,20,80,80], 'content': broken}], broken), 3, 200, 100)
    targets = pp.recovery_blocks(outcome)
    assert len(targets) == 1
    class OCR:
        enabled = True
        def extract_table_html(self, path): return fixed
    pp._recover_layout_objects(source_image, tmp_path, outcome, targets,
        GeometryClient(), False, 1, 0, glm=OCR())
    assert len(outcome['payloads']['tables']) == 1
    table = outcome['payloads']['tables'][0]
    assert table['markdown'] == fixed
    assert 'table_math_delimiter_unresolved' not in table.get('warnings', [])
    assert not outcome['layout'][0]['review_required']
    assert fixed in outcome['markdown']


def test_math_invalid_recovery_keeps_original_table(source_image, tmp_path):
    broken = '<table><tr><td>coefficient $x_{i</td></tr></table>'
    outcome = pp.build_layout_outcome(_layout_raw([
        {'label': 'table', 'bbox_2d': [20,20,80,80], 'content': broken}], broken), 3, 200, 100)
    class OCR:
        enabled = True
        def extract_table_html(self, path): return broken
    pp._recover_layout_objects(source_image, tmp_path, outcome, pp.recovery_blocks(outcome),
        GeometryClient(), False, 1, 0, glm=OCR())
    assert len(outcome['payloads']['tables']) == 1
    assert outcome['payloads']['tables'][0]['markdown'] == broken
    assert outcome['layout'][0]['review_required']


def test_recovered_table_rejects_balanced_dollars_with_broken_latex():
    block = {'layout_id': 't', 'type': 'table'}
    candidate = {**block, 'complete': True, 'status': 'EXTRACTED',
        'markdown': '<table><tr><td>$\\frac{x}{y$</td></tr></table>'}
    assert pp.validate_recovered_object(block, candidate)[0] == 'table_math_delimiter_unresolved'


def test_full_page_math_recovery_preserves_single_identity(source_image, tmp_path, monkeypatch):
    broken = '<table><tr><td>coefficient $x_{i</td></tr></table>'
    fixed = '<table><tr><td>coefficient $x_{i}$</td></tr></table>'
    calls = []
    class OCR(LayoutLedgerGLMOcrClient):
        raw = _layout_raw([{'label': 'table', 'bbox_2d': [20,20,80,80], 'content': broken}], broken)
        def extract_table_html(self, path):
            calls.append('content')
            return fixed
    class VLM(LayoutLedgerVLMClient):
        def extract_object_structured(self, path, block, compact=False):
            calls.append(block.get('recovery_target'))
            return {'layout_id': block['layout_id'], 'type': 'table', 'status': 'EXTRACTED',
                    'complete': True, 'contains_images': False, 'source_cells': [], 'image_unresolved': []}
    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', OCR)
    monkeypatch.setattr(pp, 'DynamicVLMClient', VLM)
    result = process_explicitly(str(source_image), 1, 'auto', {'provider': 'fixture'},
        {'source_page_no': 23, 'render_cleanup_with_llm': False,
         'ocr_config': {'glm_ocr': {'enabled': True}}}, None)
    assert calls == ['content', 'cell_images']
    assert len(result['elements']['tables']) == 1
    assert result['elements']['tables'][0]['markdown'] == fixed
    assert result['reconciliation']['complete']
    assert not result['reconciliation']['duplicate_layout_ids']


def test_real_dimension_crop_is_repaired_without_another_model_call(tmp_path):
    """Replay the 2026-10-28 provider crop, including its too-small cell bbox."""
    import json
    from pathlib import Path
    fixture = Path(__file__).parent / 'fixtures' / 'cell_image_crop'
    target = json.loads((fixture / 'dimension_page.json').read_text())['table']
    source = fixture / 'dimension_page.png'
    original = target['markdown']
    cells = target.pop('source_cells')
    target['image_unresolved'] = [{'reason': 'missing_cell_image_geometry'}]

    class Replay(GeometryClient):
        def extract_object_structured(self, path, block, compact=False):
            self.calls.append((path, compact))
            self.targets.append(copy.deepcopy(block))
            result = geometry(block)
            result['source_cells'] = copy.deepcopy(cells)
            # The existing recovery supplies an unpadded table crop in this case.
            page = fitz.Pixmap(str(source))
            _, crop = pp._crop_layout_block_image(source, target, tmp_path, padding_ratio=0)
            left, top, right, bottom = crop['pixel_bbox']
            for cell in result['source_cells']:
                for item in [cell, *cell['image_regions']]:
                    x0,y0,x1,y1 = item['bbox']
                    item['bbox'] = [(x0*page.width-left)/(right-left),
                                    (y0*page.height-top)/(bottom-top),
                                    (x1*page.width-left)/(right-left),
                                    (y1*page.height-top)/(bottom-top)]
                    item['bbox_space'] = 'normalized_crop'
            return result

    client = Replay()
    table, _, _ = run_recovery(source, tmp_path, target, client)
    assert len(client.calls) == 1
    assert table['markdown'] == original
    assert table['cell_image_inspection_status'] == 'complete'
    assert not table['image_unresolved']
    assert table['source_cells'][0]['image_regions'][0]['bbox'][1] * 3508 <= 1660


@pytest.mark.parametrize('edge', ['top', 'bottom', 'left', 'right'])
@pytest.mark.parametrize('size', [200, 1000])
def test_thin_dimension_stroke_cannot_cross_image_crop(edge, size):
    from PIL import Image, ImageDraw
    from importlib import import_module
    boundary = import_module(sp.__package__ + '.calculation_blocks').boundary_intersects_content
    image = Image.new('L', (size, size), 255)
    draw = ImageDraw.Draw(image)
    cut = size // 4 if edge in ('top', 'left') else 3 * size // 4
    if edge in ('top', 'bottom'):
        draw.line((size//2, cut-10, size//2, cut+10), fill=0, width=1)
    else:
        draw.line((cut-10, size//2, cut+10, size//2), fill=0, width=1)
    bbox = [.25, .25, .75, .75]
    assert boundary(image, bbox, allow_thin_rules=False)
    # Existing calculation-block separators are still permitted.
    assert not boundary(image, bbox)
    assert not boundary(image, [.1, .1, .9, .9], allow_thin_rules=False)


def test_real_json_failure_keeps_table_and_serializes_attempt_diagnostics(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    root = Path(__file__).parent / 'fixtures' / 'cell_image_crop'
    recorded = json.loads((root / 'invalid_json_result.json').read_text())
    table = recorded['table']
    class OCR(LayoutLedgerGLMOcrClient):
        raw = _layout_raw([{'label': 'table', 'bbox_2d': [10,20,90,80],
                           'content': table['markdown']}], table['markdown'])
    class VLM(LayoutLedgerVLMClient):
        def extract_object_structured(self, path, block, compact=False):
            self.last_object_call_info = {'json_status': 'invalid', 'finish_reason': 'stop',
                'response_chars': 17, 'json_error_position': 3, 'effective_max_tokens': 2048,
                'raw_response': 'DO_NOT_PERSIST'}
            return {}
    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', OCR)
    monkeypatch.setattr(pp, 'DynamicVLMClient', VLM)
    result = process_explicitly(str(root / 'dimension_page.png'), 1, 'auto', {'provider': 'fixture'},
        {'source_page_no': 8, 'render_cleanup_with_llm': False, 'layout_ledger_enabled': True,
         'figure_semantic_description_required': False, 'ocr_config': {'glm_ocr': {'enabled': True}}}, None)
    actual = result['elements']['tables'][0]
    assert actual['markdown'] == table['markdown']
    assert actual['image_unresolved'] == table['image_unresolved']
    assert actual.get('cell_image_inspection_status') != 'complete'
    attempts = result['cell_image_recovery']['objects'][0]['attempts']
    assert len(attempts) == 2
    assert all(a['reason'] == 'response_json_invalid' and a['json_error_position'] == 3 for a in attempts)
    assert 'DO_NOT_PERSIST' not in json.dumps(result)


@pytest.mark.parametrize('attempt', [0, 1])
def test_real_clipped_json_is_repaired_from_source_pixels(tmp_path, attempt):
    import json
    from pathlib import Path
    root = Path(__file__).parent / 'fixtures' / 'cell_image_crop'
    table = json.loads((root / 'dimension_page.json').read_text())['table']
    table.pop('source_cells')
    recorded = json.loads((root / 'clipped_json_attempts.json').read_text())
    response = geometry(table)
    response['source_cells'] = copy.deepcopy(recorded['attempts'][attempt])
    for cell in response['source_cells']:
        cell['image_regions'] = cell.pop('regions')
        for region in cell['image_regions']:
            region['image_id'] = 'recorded-drawing'
    reason, recovered = pp._validate_cell_image_recovery(table, response, recorded['crop'], root / 'dimension_page.png')
    assert reason == ''
    assert recovered['markdown'] == table['markdown']
    cell = recovered['source_cells'][0]
    region = cell['image_regions'][0]
    # Source top of the detached "10" dimension is above both rejected boxes.
    assert region['bbox'][1] * 3508 <= 1660
    assert cell['bbox'][1] <= region['bbox'][1]
    assert region['image_id'] == 'recorded-drawing'
    assert recovered['cell_image_inspection_status'] == 'complete'
    payload = {'tables': [recovered], 'figures': []}
    pp._attach_figure_assets(root / 'dimension_page.png', payload, 8)
    figure = payload['figures'][0]
    assert figure['bbox'] == region['bbox']
    assert figure['image_asset']['status'] == 'available'
    assert figure['image_asset']['height'] > 850



@pytest.mark.parametrize('edge', [0, 1, 2, 3])
@pytest.mark.parametrize('size', [400, 1200])
def test_auto_crop_expansion_is_bounded_and_preserves_complete_crops(edge, size):
    from PIL import Image, ImageDraw
    boundary = importlib.import_module(sp.__package__ + '.calculation_blocks')
    image = Image.new('L', (size, size), 255)
    draw = ImageDraw.Draw(image)
    # A thin extension of a drawing crosses each possible proposed edge.
    axis, direction = edge % 2, -1 if edge < 2 else 1
    cut = .3 if edge < 2 else .7
    points = [(int(size*.5), int(size*(cut-.04))), (int(size*.5), int(size*(cut+.04)))]
    if axis == 0:
        points = [(y,x) for x,y in points]
    draw.line(points, fill=0, width=max(1,size//400))
    bbox = [.3,.3,.7,.7]
    repaired = boundary.expand_clipped_image_bbox(image, bbox, [.1,.1,.9,.9])
    assert repaired is not None
    assert (repaired[edge] - bbox[edge]) * direction > .04
    assert not boundary.boundary_intersects_content(image, repaired, allow_thin_rules=False)
    assert boundary.expand_clipped_image_bbox(image, repaired, [.1,.1,.9,.9]) == repaired
    # No room beyond the table / no nearby blank boundary must retain the error.
    assert boundary.expand_clipped_image_bbox(image, bbox, bbox) is None
    solid = Image.new('L', (size,size), 0)
    assert boundary.expand_clipped_image_bbox(solid, bbox, [.1,.1,.9,.9]) is None


def test_single_page_assets_do_not_implicitly_recover_images(source_image):
    ctx = sp.SinglePageContext(source_path=source_image, image_path=source_image, input_type='image', page_no=3, page_text='')
    client = GeometryClient()
    calls = {'glm_ocr': 0, 'vlm_ocr': 0}
    sp._attach_single_page_figure_assets(ctx, [], [table_target()], client, calls, 1)
    assert calls == {'glm_ocr': 0, 'vlm_ocr': 0}
    assert client.calls == []


def test_structure_target_requires_explicit_provider_plan(source_image, tmp_path, monkeypatch):
    import hashlib
    def unexpected(*args, **kwargs):
        raise AssertionError('provider must not be initialized without an explicit plan')
    monkeypatch.setattr(sp, 'DynamicVLMClient', unexpected)
    ctx = sp.SinglePageContext(source_path=source_image, image_path=source_image, input_type='image', page_no=1, page_text='')
    target = {**table_target(), 'type': 'table', 'page_no': 1,
              'source_sha1': hashlib.sha1(source_image.read_bytes()).hexdigest(), 'max_model_calls': 2}
    result = sp._recover_structure_target('extract_page_tables', 'tables', ctx, target, 'en', {}, {}, tmp_path)
    assert result['structure_recovery']['reason'] == 'recovery_provider_plan_required'
    assert result['model_calls'] == {'glm_ocr': 0, 'vlm_ocr': 0}


def test_non_layout_successive_recoveries_preserve_previous_tables(tmp_path, monkeypatch):
    path = tmp_path / 'page.pdf'
    doc = fitz.open(); page = doc.new_page(width=100, height=100)
    page.draw_rect(fitz.Rect(20, 20, 80, 80), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(path); doc.close()
    calls = []
    class OCR(LayoutLedgerGLMOcrClient):
        def extract_page(self, source):
            calls.append(source)
            return sp.OcrResult(markdown='page', tables=[
                sp.OcrElement(kind='table', source='glm_ocr', markdown='<table><tr><td>A</td></tr></table>',
                              raw={'bbox': [.1, .1, .9, .4], 'bbox_space': 'normalized_page'}),
                sp.OcrElement(kind='table', source='glm_ocr', markdown='<table><tr><td>B</td></tr></table>',
                              raw={'bbox': [.1, .5, .9, .9], 'bbox_space': 'normalized_page'})])
    def recover(image_path, output_dir, payloads, vlm, enabled, max_objects, **kwargs):
        for table in payloads['tables']:
            table.update(cell_image_inspection_status='complete', image_unresolved=[])
        return 0, 0, {'pending': len(payloads['tables']), 'attempted': len(payloads['tables']), 'objects': []}
    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', OCR)
    monkeypatch.setattr(pp, 'DynamicVLMClient', LayoutLedgerVLMClient)
    monkeypatch.setattr(pp, '_recover_missing_table_images', recover)
    config = {'source_page_no': 7, 'render_dpi': 150, 'layout_ledger_enabled': False,
              'ocr_config': {'glm_ocr': {'enabled': True}}}
    first = pp.process_page(str(path), 1, 'auto', {'provider': 'fixture'}, config, None)
    ids = [table['layout_id'] for table in first['rag']['elements']['tables']]
    assert len(ids) == 2
    def retry(state, target):
        return pp.process_page(str(path), 1, 'auto', {'provider': 'fixture'},
            {**config, 'docs_recovery_phase': 'recover', '__docs_saved_layout': state,
             'docs_recovery_selection': {'table_images': [target], 'image_provider_plan': ['vlm_ocr'],
                                         'image_model_budget': 1}}, None)
    second = retry(first['_docs_raw_layout'], ids[0])
    import json
    json.dumps(second['_docs_raw_layout'])
    third = retry(second['_docs_raw_layout'], ids[1])
    assert [table.get('cell_image_inspection_status') for table in third['rag']['elements']['tables']] == ['complete', 'complete']
    assert len(calls) == 1


def test_selected_table_image_attempt_reuses_table_and_runs_one_model(source_image, tmp_path, monkeypatch):
    import hashlib
    client = GeometryClient()
    monkeypatch.setattr(sp, 'DynamicVLMClient', lambda config: client)
    ctx = sp.SinglePageContext(source_path=source_image, image_path=source_image, input_type='image', page_no=3, page_text='')
    table = table_target()
    target = {'table': table, 'source_sha1': hashlib.sha1(source_image.read_bytes()).hexdigest(),
              'page_no': 3, 'provider': 'vlm_ocr'}
    result = sp._recover_single_table_image('extract_page_tables', ctx, target, 'en', {}, {}, tmp_path)
    assert result['model_calls'] == {'glm_ocr': 0, 'vlm_ocr': 1}
    assert len(client.calls) == 1
    assert result['items'][0]['markdown'] == table['markdown']
    assert result['items'][0]['layout_id'] == table['layout_id']
    assert result['figures'][0]['image_asset']['status'] == 'available'


def test_asme_p5_recorded_cell_image_regions_keep_three_drawings():
    import json
    from pathlib import Path
    root = Path(__file__).parent / 'fixtures' / 'cell_image_crop'
    recorded = json.loads((root / 'asme_p5_recorded.json').read_text())
    table = recorded['table']
    response = geometry(table)
    response['source_cells'] = copy.deepcopy(recorded['cells'])
    for cell in response['source_cells']:
        cell.pop('has_image_id', None)
        cell['image_regions'] = cell.pop('regions')
        for region in cell['image_regions']:
            region.pop('has_image_id', None)
            region['image_id'] = 'drawing-' + str(cell['row'])
    reason, recovered = pp._validate_cell_image_recovery(table, response, recorded['crop'], root / 'asme_p5_page.png')
    assert reason == ''
    assert len(recovered['source_cells']) == 3
    assert recovered['markdown'] == table['markdown']
    # Reviewed ink extents include the detached dimension labels and row-3 note.
    expected = [(1627, 646, 2005, 1046), (1505, 1103, 2128, 1575), (1433, 1627, 2202, 2017)]
    from PIL import Image
    with Image.open(root / 'asme_p5_page.png') as image:
        for cell, (x0, y0, x1, y1) in zip(recovered['source_cells'], expected):
            box = cell['image_regions'][0]['bbox']
            actual = [round(v * scale) for v, scale in zip(box, image.size * 2)]
            assert actual[0] <= x0 and actual[1] <= y0
            assert actual[2] >= x1 and actual[3] >= y1
    payload = {'tables': [recovered], 'figures': []}
    pp._attach_figure_assets(root / 'asme_p5_page.png', payload, 5)
    assert len(payload['figures']) == 3
    assert all(f['image_asset']['status'] == 'available' for f in payload['figures'])


def test_long_drawing_stroke_is_not_mistaken_for_a_table_separator():
    from PIL import Image, ImageDraw
    from importlib import import_module
    blocks = import_module(sp.__package__ + '.calculation_blocks')
    image = Image.new('L', (400, 400), 255)
    draw = ImageDraw.Draw(image)
    draw.line((120, 45, 120, 355), fill=0, width=2)
    draw.line((150, 150, 250, 150), fill=0, width=2)
    original = [100, 100, 300, 300]
    assert blocks._trim_crossed_table_rules(image, original, [40, 40, 360, 360], 4) == original


def test_table_separator_is_not_trimmed_when_it_would_remove_adjacent_content():
    from PIL import Image, ImageDraw
    from importlib import import_module
    blocks = import_module(sp.__package__ + '.calculation_blocks')
    image = Image.new('L', (400, 400), 255)
    draw = ImageDraw.Draw(image)
    for x in (80, 120, 320): draw.line((x, 60, x, 340), fill=0, width=2)
    for y in (60, 200, 340): draw.line((80, y, 320, y), fill=0, width=2)
    draw.rectangle((105, 110, 110, 120), fill=0)
    original = [100, 90, 300, 180]
    result = blocks._trim_crossed_table_rules(image, original, [80, 60, 321, 341], 4)
    assert result[0] == original[0]


def test_long_dimension_inside_grid_is_not_trimmed_as_a_column():
    from PIL import Image, ImageDraw
    from importlib import import_module
    blocks = import_module(sp.__package__ + '.calculation_blocks')
    image = Image.new('L', (400, 400), 255)
    draw = ImageDraw.Draw(image)
    for x in (40, 360): draw.line((x, 40, x, 360), fill=0, width=2)
    for y in (40, 360): draw.line((40, y, 360, y), fill=0, width=2)
    draw.line((118, 42, 118, 358), fill=0, width=2)
    draw.rectangle((180, 150, 250, 250), outline=0, width=2)
    original = [.25, .2, .75, .8]
    result = blocks.expand_clipped_image_bbox(image, original, [.1, .1, .905, .905])
    assert result is None or result[0] <= 118 / 400


def test_drawing_line_in_multirow_grid_is_not_removed_when_grid_count_conflicts():
    from PIL import Image, ImageDraw
    from importlib import import_module
    blocks = import_module(sp.__package__ + '.calculation_blocks')
    image = Image.new('L', (400, 400), 255)
    draw = ImageDraw.Draw(image)
    for x in (40, 360): draw.line((x, 40, x, 360), fill=0, width=2)
    for y in (40, 145, 250, 360): draw.line((40, y, 360, y), fill=0, width=2)
    draw.line((118, 42, 118, 358), fill=0, width=2)
    original = [100, 80, 300, 320]
    assert blocks._trim_crossed_table_rules(image, original, [40, 40, 362, 362], 4, (3, 1)) == original
