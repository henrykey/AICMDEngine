from types import SimpleNamespace

import importlib
import sys
import types
from pathlib import Path

package = types.ModuleType("pdf2md_page_figure_testpkg")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "mcp/servers/PDF2MDEnhanced")]
sys.modules[package.__name__] = package
page_processor = importlib.import_module(package.__name__ + ".page_processor")
single_page_tools = importlib.import_module(package.__name__ + ".single_page_tools")


def test_full_page_figures_reuse_one_page_call_and_keep_existing_caption(monkeypatch):
    calls = []
    def fake(ctx, figures, blocks, vlm, counts, warnings):
        calls.append((ctx.image_path, figures, blocks))
        counts['vlm_ocr'] += 1
        return [{**figure, 'description': f'description-{figure["block_index"]}',
                 'caption': 'unverified model caption'} for figure in figures]
    monkeypatch.setattr(single_page_tools, '_enhance_layout_figures_with_vlm', fake)
    page = {'markdown': '图8-17 固定管板式热交换器设计系数', 'layout': [], 'payloads': {'figures': [
        {'layout_id': 'p30-o001-figure', 'bbox': [.205, .129, .795, .708], 'caption': '图8-17 原图题', 'description': '', 'semantic_status': 'missing', 'missing_fields': ['description']},
        {'layout_id': 'p30-o002-figure', 'bbox': [.1, .72, .8, .9], 'description': ''},
        {'layout_id': 'existing', 'bbox': [.1, .1, .2, .2], 'description': 'existing description'},
    ]}}
    assert page_processor._describe_missing_page_figures('/tmp/page.png', page, SimpleNamespace(enabled=True), 'zh') == 1
    assert len(calls) == 1 and len(calls[0][1]) == 2
    figures = page['payloads']['figures']
    assert figures[0]['description'] == 'description-1'
    assert figures[0]['caption'] == '图8-17 原图题'
    assert figures[0]['missing_fields'] == []
    assert figures[0]['semantic_status'] == 'complete'
    assert figures[1]['description'] == 'description-2'
    assert figures[2]['description'] == 'existing description'


def test_no_missing_figure_means_no_model_call(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('model should not be called')
    monkeypatch.setattr(single_page_tools, '_enhance_layout_figures_with_vlm', fail)
    page = {'payloads': {'figures': [{'bbox': [.1, .1, .2, .2], 'description': 'already described'}]}}
    assert page_processor._describe_missing_page_figures('/tmp/page.png', page, SimpleNamespace(enabled=True), 'zh') == 0


def test_full_page_extraction_carries_reused_page_semantics_to_output(monkeypatch):
    spec = importlib.util.spec_from_file_location("figure_fixture", Path(__file__).with_name("test_pdf2md_enhanced_bad_text_policy.py"))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    tools = importlib.import_module(fixture.PACKAGE_NAME + '.single_page_tools')
    calls = []
    def fake(ctx, figures, blocks, vlm, counts, warnings):
        calls.append(len(figures))
        counts['vlm_ocr'] += 1
        return [{**figure, 'description': '曲线图显示设计系数与参数的关系'} for figure in figures]
    monkeypatch.setattr(tools, '_enhance_layout_figures_with_vlm', fake)
    raw = fixture._layout_raw([
        {'index': 1, 'label': 'image', 'bbox_2d': [20, 13, 80, 71], 'content': ''},
        {'index': 2, 'label': 'text', 'bbox_2d': [34, 75, 67, 77], 'content': '图8-17 固定管板式热交换器设计系数'},
    ])
    result = fixture._run_layout_ledger_page(monkeypatch, raw)
    assert calls == [1]
    assert result['elements']['figures'][0]['description'] == '曲线图显示设计系数与参数的关系'
    assert result['decision']['vlm_calls'] == 1
    assert not any(item.get('collection') == 'figures' and 'description' in item.get('missing_fields', [])
                   for item in result['semantic_status'].get('objects', []))


def test_recovered_description_and_asset_reconcile_existing_figure():
    ledger = importlib.import_module(package.__name__ + '.layout_ledger')
    box = [.205242, .128848, .795161, .708096]
    layout = [{'layout_id': 'p30-o001-figure', 'type': 'figure', 'status': 'FAILED',
               'review_required': True, 'bbox': box, 'bbox_space': 'normalized_page',
               'error': {'code': 'layout_figure_content_missing', 'stage': 'layout_content'}}]
    figure = {'layout_id': 'p30-o001-figure', 'bbox': box, 'bbox_space': 'normalized_page',
              'content_status': 'geometry_only', 'semantic_status': 'complete',
              'description': '曲线图说明', 'image_asset': {'status': 'available', 'layout_id': 'p30-o001-figure'}}
    result = ledger.reconcile_layout('EXTRACTED', layout, {'figures': [figure], 'tables': [], 'formulas': []})
    assert result['complete'] is True
    assert layout[0]['status'] == 'EXTRACTED'
    assert layout[0]['error'] is None
    assert layout[0]['review_required'] is False


def test_calculation_table_mislabelled_text_is_preserved_as_table():
    ledger = importlib.import_module(package.__name__ + '.layout_ledger')
    source = ('Table 4.18.4\nEvaluation of F min and F max\n'
              'Calculate the functions.\n$$Z_d(x)=x$$\nCalculate the minimum.\n$$F_t(x)=y$$')
    raw = {'md_results': source, 'data_info': {'width': 100, 'height': 100},
           'layout_details': [[{'index': 1, 'label': 'text', 'bbox_2d': [8, 9, 88, 53], 'content': source}]]}
    outcome = ledger.build_layout_outcome(raw, 23, 100, 100)
    assert len(outcome['payloads']['tables']) == 1
    assert outcome['payloads']['tables'][0]['markdown'] == source
    assert 'Table 4.18.4' in outcome['payloads']['tables'][0]['title']
    assert outcome['layout'][0]['type'] == 'table'


def test_ordinary_calculation_prose_is_not_invented_as_table():
    ledger = importlib.import_module(package.__name__ + '.layout_ledger')
    source = 'Calculate the functions.\n$$Z_d(x)=x$$\nCalculate the minimum.\n$$F_t(x)=y$$'
    raw = {'md_results': source, 'data_info': {'width': 100, 'height': 100},
           'layout_details': [[{'index': 1, 'label': 'text', 'bbox_2d': [8, 9, 88, 53], 'content': source}]]}
    outcome = ledger.build_layout_outcome(raw, 23, 100, 100)
    assert outcome['payloads']['tables'] == []


def test_real_asme_page23_text_block_keeps_calculation_source():
    import json
    ledger = importlib.import_module(package.__name__ + '.layout_ledger')
    raw = json.loads((Path(__file__).parent / 'fixtures' / 'asme_page23_calculation_text.json').read_text())
    outcome = ledger.build_layout_outcome(raw, 23, 1000, 1000)
    assert len(outcome['payloads']['tables']) == 1
    table = outcome['payloads']['tables'][0]
    assert table['title'].startswith('Table 4.18.4 Evaluation of')
    assert table['markdown'] == raw['layout_details'][0][0]['content']


def test_real_asme_page23_calculation_is_in_page_output(monkeypatch):
    import json
    spec = importlib.util.spec_from_file_location('calculation_fixture', Path(__file__).with_name('test_pdf2md_enhanced_bad_text_policy.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    raw = json.loads((Path(__file__).parent / 'fixtures' / 'asme_page23_calculation_text.json').read_text())
    result = fixture._run_layout_ledger_page(monkeypatch, raw)
    assert len(result['elements']['tables']) == 1
    assert result['elements']['tables'][0]['title'].startswith('Table 4.18.4 Evaluation of')
    assert result['elements']['tables'][0]['markdown'] == raw['layout_details'][0][0]['content']


def test_figure_without_description_or_asset_stays_unresolved():
    ledger = importlib.import_module(package.__name__ + '.layout_ledger')
    box = [.2, .1, .8, .7]
    for description, asset in [('', {'status': 'available', 'layout_id': 'p30-o001-figure'}),
                               ('曲线图说明', {'status': 'missing'})]:
        layout = [{'layout_id': 'p30-o001-figure', 'type': 'figure', 'status': 'FAILED',
                   'review_required': True, 'bbox': box, 'bbox_space': 'normalized_page',
                   'error': {'code': 'layout_figure_content_missing', 'stage': 'layout_content'}}]
        figure = {'layout_id': 'p30-o001-figure', 'bbox': box, 'bbox_space': 'normalized_page',
                  'content_status': 'geometry_only', 'semantic_status': 'complete',
                  'description': description, 'image_asset': asset}
        result = ledger.reconcile_layout('EXTRACTED', layout, {'figures': [figure], 'tables': [], 'formulas': []})
        assert result['complete'] is False
