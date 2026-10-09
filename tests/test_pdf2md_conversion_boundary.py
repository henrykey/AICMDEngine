"""Conversion returns source to Docs without starting a business enhancement chain."""
import pytest
from tests.test_pdf2md_enhanced_bad_text_policy import (
    page_processor as pp, _run_layout_ledger_page, _layout_raw, LayoutLedgerGLMOcrClient,
)


def test_page_conversion_keeps_source_and_layout_without_business_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('conversion must return control to Docs')
    for name in ('_enrich_upload_semantics', 'complete_calculation_batch', '_recover_formula_numbers',
                 '_recover_missing_table_images', '_recover_cell_figure_semantics', '_recover_layout_objects',
                 '_recover_unbound_table_regions'):
        monkeypatch.setattr(pp, name, forbidden, raising=False)
    source = '| Input | Value |\n| --- | --- |\n| p | 12 MPa |'
    out = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {'index': 1, 'label': 'table', 'bbox_2d': [10, 20, 90, 80], 'content': source}], markdown=source))
    table = out['elements']['tables'][0]
    assert table['markdown'] == source
    assert table['layout_id'] == out['layout'][0]['layout_id']
    assert table['bbox_space'] == 'normalized_page'
    assert 'table_kind' not in table and 'calculation_sheet' not in table
    assert out['decision']['vlm_calls'] == 0
    assert out['decision']['glm_calls'] == 1
    assert out['semantic_status']['reason'] == 'docs_semantics_pending'


def test_incomplete_object_source_is_not_hidden_by_pending_semantics(monkeypatch):
    source = '<table><tr><td>Known value</td></tr>'
    out = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {'index': 1, 'label': 'table', 'bbox_2d': [10, 10, 90, 90], 'content': source},
        {'index': 2, 'label': 'formula', 'bbox_2d': [10, 91, 90, 99], 'content': 'F=ma'},
    ], markdown=source + '\nF=ma'), recovered={})
    assert out['decision']['vlm_calls'] == 0
    assert out['semantic_status']['complete'] is False
    assert out['semantic_status']['reason'] == 'layout_objects_incomplete'
    assert source in out['render']['markdown']


def test_layout_failure_keeps_readable_ocr_without_second_call(monkeypatch):
    out = _run_layout_ledger_page(monkeypatch, _layout_raw([], markdown='Readable source retained.'), recovered={})
    assert out['render']['markdown'] == 'Readable source retained.'
    assert out['decision']['glm_calls'] == 1
    assert out['decision']['vlm_calls'] == 0
    assert out['reconciliation']['complete'] is False
    assert out['semantic_status']['complete'] is False


@pytest.mark.parametrize("asset_case", ["available", "unresolved", "foreign"])
def test_available_figure_crop_completes_source_coverage_without_semantics(tmp_path, asset_case):
    from PIL import Image
    from tests.test_pdf2md_enhanced_object_recovery import ledger
    image = tmp_path / 'page.png'
    Image.new('RGB', (100, 100), 'white').save(image)
    outcome = ledger.build_layout_outcome(_layout_raw([
        {'label': 'image', 'bbox_2d': [10, 10, 90, 90], 'content': ''},
    ]), 1, 100, 100)
    pp._attach_figure_assets(image, outcome['payloads'], 1)
    output = pp._build_layout_output_elements('', outcome['payloads'], 'full_glm_ocr')
    figure = output['figures'][0]
    assert figure['image_asset']['status'] == 'available'
    if asset_case == 'unresolved':
        figure['image_asset']['status'] = 'unresolved'
    elif asset_case == 'foreign':
        figure['image_asset']['layout_id'] = 'foreign-object'
    result = ledger.reconcile_layout(outcome['layout_status'], outcome['layout'], output)
    assert result['complete'] is (asset_case == 'available')
    assert figure['semantic_status'] == 'missing'
    assert figure['description'] == ''
    assert outcome['layout'][0]['payload_ref'] == {'collection': 'figures', 'index': 0}


def test_shared_docs_conversion_fixture_matches_producer(monkeypatch):
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / 'fixtures/docs_conversion_boundary.json').read_text())
    source = fixture['source']
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {'index': 1, 'label': 'table', 'bbox_2d': [10, 20, 90, 80], 'content': source}], markdown=source))
    assert {key: result[key] for key in fixture['page_result']} == fixture['page_result']
    assert result['decision']['vlm_calls'] == 0
    assert result['decision']['glm_calls'] == 1
