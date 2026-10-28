import copy
import importlib
import json
from pathlib import Path

import pytest
from PIL import Image
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools as sp

pp = importlib.import_module(sp.__package__ + '.page_processor')
cb = importlib.import_module(sp.__package__ + '.calculation_blocks')
vc = importlib.import_module(sp.__package__ + '.vlm_client')
ROOT = Path(__file__).parent / 'fixtures' / 'full_run_recovery'


def test_real_crop_recovers_dimensions_without_the_adjacent_table_rule():
    recorded = json.loads((ROOT / 'clipped.json').read_text())
    table = recorded['table']
    obj = recorded['recovery']['objects'][0]
    cell = copy.deepcopy(obj['attempts'][2]['cell_geometry'][0])
    cell['image_regions'] = [{**cell.pop('regions')[0], 'image_id': 'diagram'}]
    response = {'layout_id': table['layout_id'], 'type': 'table', 'complete': True,
                'status': 'EXTRACTED', 'contains_images': True, 'source_cells': [cell]}
    reason, recovered = pp._validate_cell_image_recovery(table, response, obj['crop'], ROOT / 'clipped.png')
    assert reason == ''
    region = next(c for c in recovered['source_cells'] if c.get('image_regions'))['image_regions'][0]
    with Image.open(ROOT / 'clipped.png') as image:
        assert not cb.boundary_intersects_content(image, region['bbox'], allow_thin_rules=False)
        left, top, right, bottom = [round(v * scale) for v, scale in zip(region['bbox'], image.size * 2)]
    # Source extrema of the left thickness label and outer right dimensions.
    assert left <= 306 and right >= 1123
    assert top <= 2440 and bottom >= 3135


def test_physical_caps_are_per_object_and_content_or_image_operation():
    client = vc.DynamicVLMClient({'_calculation_processing': 'single_operation',
                                 'table_analysis_max_physical_requests': 2})
    for key in [('first', 'cell_images'), ('second', 'cell_images'), ('third', 'cell_images'),
                ('first', 'content')]:
        client.recovery_budget_key = key
        client._count_physical_request(None)
        client._count_physical_request(None)
        with pytest.raises(vc.PhysicalRequestBudgetExceeded):
            client._count_physical_request(None)
    client.recovery_budget_key = ('first', 'cell_images')
    with pytest.raises(vc.PhysicalRequestBudgetExceeded):
        client._count_physical_request(None)
    assert client.physical_requests == 8


def test_real_watermark_fragment_is_not_materialized_as_a_figure():
    table = {'layout_id': 'watermark-table', 'type': 'table', 'bbox': [0, 0, 1, 1],
             'bbox_space': 'normalized_page', 'markdown': '<table><tr><td></td></tr></table>'}
    cell = {'row': 0, 'col': 0, 'rowspan': 1, 'colspan': 1, 'bbox': [0, 0, 1, 1],
            'bbox_space': 'normalized_crop', 'image_regions': [{'image_id': 'candidate',
            'bbox': [.1, .1, .9, .9], 'bbox_space': 'normalized_crop'}]}
    response = {'layout_id': table['layout_id'], 'type': 'table', 'complete': True,
                'status': 'EXTRACTED', 'contains_images': True, 'source_cells': [cell]}
    reason, result = pp._validate_cell_image_recovery(table, response,
                {'pixel_bbox': [0, 0, 79, 98]}, ROOT / 'watermark-only.png')
    assert reason == 'cell_image_nonvisual_content'
    assert result is None
    # Existing bounded retry can conclusively return no cell illustrations.
    response.update(contains_images=False, source_cells=[])
    reason, result = pp._validate_cell_image_recovery(table, response,
                {'pixel_bbox': [0, 0, 79, 98]}, ROOT / 'watermark-only.png')
    assert reason == '' and result['contains_images'] is False


def test_formula_image_reuses_object_recovery_and_preserves_ledger_identity(tmp_path):
    recorded = json.loads((ROOT / 'formula.json').read_text())
    entry = copy.deepcopy(recorded['layout'][0])
    outcome = {'layout': [entry], 'payloads': {'tables': [], 'formulas': [],
                'figures': [{**entry, 'content_status': 'geometry_only'}]}, 'markdown': ''}
    class Provider:
        last_object_call_info = {}
        def extract_object_structured(self, path, block, compact=False):
            assert Path(path).is_file()
            return {'layout_id': block['layout_id'], 'type': 'formula', 'complete': True,
                    'status': 'EXTRACTED', 'latex': r"$$A_d=n'\left(S_n\times S-\frac{\sqrt{3}}{2}S^2\right)$$",
                    'description': '用于计算管板分程处面积。'}
    _, calls, diagnostic = pp._recover_layout_objects(ROOT / 'formula.png', tmp_path, outcome,
        [{**entry, 'recovery_target': 'visual_type'}], Provider(), True, 8, .02)
    assert calls == 1
    assert outcome['payloads']['figures'] == []
    assert len(outcome['payloads']['formulas']) == 1
    assert outcome['payloads']['formulas'][0]['layout_id'] == entry['layout_id']
    assert outcome['layout'][0]['type'] == 'formula'
    assert diagnostic['objects'][0]['outcome'] == 'recovered'


def test_real_watermark_plus_table_rule_is_not_a_drawing():
    recorded = json.loads((ROOT / 'watermark-table.json').read_text())
    obj = recorded['recovery']['objects'][0]
    cell = copy.deepcopy(obj['attempts'][0]['cell_geometry'][0])
    cell['image_regions'] = [{**cell.pop('regions')[0], 'image_id': 'candidate'}]
    table = recorded['table']
    response = {'layout_id': table['layout_id'], 'type': 'table', 'complete': True,
                'status': 'EXTRACTED', 'contains_images': True, 'source_cells': [cell]}
    reason, result = pp._validate_cell_image_recovery(table, response, obj['crop'], ROOT / 'watermark-table.png')
    assert reason == 'cell_image_nonvisual_content'
    assert result is None


def test_page_conversion_verifies_the_real_equation_image_before_materialization(monkeypatch):
    from tests.test_pdf2md_enhanced_bad_text_policy import LayoutLedgerGLMOcrClient, LayoutLedgerVLMClient, _layout_raw
    entry = json.loads((ROOT / 'formula.json').read_text())['layout'][0]
    class OCR(LayoutLedgerGLMOcrClient):
        raw = _layout_raw([{'label': 'image', 'bbox_2d': [v * 100 for v in entry['bbox']], 'content': ''}])
    class VLM(LayoutLedgerVLMClient):
        def extract_object_structured(self, path, block, compact=False):
            assert block['recovery_target'] == 'visual_type'
            return {'layout_id': block['layout_id'], 'type': 'formula', 'complete': True,
                    'status': 'EXTRACTED', 'latex': r"$$A_d=n'\left(S_n\times S-\frac{\sqrt{3}}{2}S^2\right)$$",
                    'description': '用于计算分程处面积。'}
    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', OCR)
    monkeypatch.setattr(pp, 'DynamicVLMClient', VLM)
    result = pp.process_page(str(ROOT / 'formula.png'), 1, 'auto', {'provider': 'fixture'},
        {'source_page_no': 11, 'render_dpi': 300, 'render_cleanup_with_llm': False,
         'ocr_config': {'glm_ocr': {'enabled': True}}}, None)
    assert len(result['elements']['formulas']) == 1
    assert result['elements']['figures'] == []
    assert result['layout'][0]['type'] == 'formula'


def test_failed_type_verification_keeps_original_visual_and_specific_issue(tmp_path):
    entry = copy.deepcopy(json.loads((ROOT / 'formula.json').read_text())['layout'][0])
    outcome = {'layout': [entry], 'payloads': {'tables': [], 'formulas': [],
                'figures': [{**entry, 'content_status': 'geometry_only'}]}, 'markdown': ''}
    class Provider:
        def extract_object_structured(self, *args, **kwargs):
            return {}
    pp._recover_layout_objects(ROOT / 'formula.png', tmp_path, outcome,
        [{**entry, 'recovery_target': 'visual_type'}], Provider(), True, 8, .02)
    assert outcome['payloads']['formulas'] == []
    assert outcome['payloads']['figures'][0]['bbox'] == entry['bbox']
    assert outcome['payloads']['figures'][0]['warnings'] == ['visual_type_unverified']
