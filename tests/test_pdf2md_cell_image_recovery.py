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


@pytest.mark.parametrize("layout_enabled", [True, False])
@pytest.mark.parametrize("figure_semantics", [True, False])
def test_conversion_preserves_complete_table_and_inspects_cell_images(tmp_path, monkeypatch, layout_enabled, figure_semantics):
    path = tmp_path / 'page.pdf'
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(fitz.Rect(30, 30, 70, 70), color=(1, 0, 0), fill=(1, 0, 0))
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
    result = pp.process_page(str(path), 1, 'auto', {'provider': 'fixture'},
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
    sp._attach_single_page_figure_assets(ctx, figures, tables, GeometryClient(), calls, 1)
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

    class OCR(LayoutLedgerGLMOcrClient):
        def extract_page(self, source):
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
        return 0, 1, {}

    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', OCR)
    monkeypatch.setattr(pp, 'DynamicVLMClient', LayoutLedgerVLMClient)
    monkeypatch.setattr(pp, '_recover_missing_table_images', recover)
    result = pp.process_page(str(path), 1, 'auto', {'provider': 'fixture'},
        {'source_page_no': 7, 'render_dpi': 150, 'render_cleanup_with_llm': False,
         'layout_ledger_enabled': False, 'ocr_config': {'glm_ocr': {'enabled': True}}}, None)

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


def test_structure_target_shares_its_explicit_budget(source_image, tmp_path, monkeypatch):
    import hashlib
    class VLM(GeometryClient):
        def __init__(self, cfg):
            super().__init__()
        def extract_table_html(self, path, block, compact=False):
            self.last_object_call_info = {'json_status': 'html', 'finish_reason': 'stop'}
            return HTML
    monkeypatch.setattr(sp, 'DynamicVLMClient', VLM)
    ctx = sp.SinglePageContext(source_path=source_image, image_path=source_image, input_type='image', page_no=1, page_text='')
    target = {**table_target(), 'type': 'table', 'page_no': 1,
              'source_sha1': hashlib.sha1(source_image.read_bytes()).hexdigest(), 'max_model_calls': 2}
    out = sp._recover_structure_target('extract_page_tables', 'tables', ctx, target, 'en', {}, {}, tmp_path)
    assert out['model_calls'] == {'glm_ocr': 0, 'vlm_ocr': 2}
    assert out['structure_recovery']['status'] == 'complete'
    assert out['figures'][0]['image_asset']['status'] == 'available'
    target['max_model_calls'] = 1
    out = sp._recover_structure_target('extract_page_tables', 'tables', ctx, target, 'en', {}, {}, tmp_path)
    assert out['model_calls'] == {'glm_ocr': 0, 'vlm_ocr': 1}
    assert out['structure_recovery']['status'] == 'unresolved'
    assert out['figures'] == []


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
