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
    result = fixture._run_layout_ledger_page(monkeypatch, raw, recovered={'tables': [], 'formulas': [], 'figures': []})
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


def test_calculation_text_is_preserved_for_docs_classification():
    ledger = importlib.import_module(package.__name__ + '.layout_ledger')
    source = ('Table 4.18.4\nEvaluation of F min and F max\n'
              'Calculate the functions.\n$$Z_d(x)=x$$\nCalculate the minimum.\n$$F_t(x)=y$$')
    raw = {'md_results': source, 'data_info': {'width': 100, 'height': 100},
           'layout_details': [[{'index': 1, 'label': 'text', 'bbox_2d': [8, 9, 88, 53], 'content': source}]]}
    outcome = ledger.build_layout_outcome(raw, 23, 100, 100)
    assert outcome['payloads']['tables'] == []
    assert outcome['layout'][0]['type'] == 'text'
    assert outcome['layout'][0]['content'] == source


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
    assert outcome['payloads']['tables'] == []
    assert outcome['layout'][0]['type'] == 'text'
    assert outcome['layout'][0]['content'] == raw['layout_details'][0][0]['content']


def test_real_asme_page23_calculation_is_in_page_output(monkeypatch):
    import json
    spec = importlib.util.spec_from_file_location('calculation_fixture', Path(__file__).with_name('test_pdf2md_enhanced_bad_text_policy.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    raw = json.loads((Path(__file__).parent / 'fixtures' / 'asme_page23_calculation_text.json').read_text())
    result = fixture._run_layout_ledger_page(monkeypatch, raw)
    assert result['elements']['tables'] == []
    assert result['layout'][0]['type'] == 'text'
    assert result['layout'][0]['content'] == raw['layout_details'][0][0]['content']


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


def test_two_step_reuses_layout_and_batches_selected_figures(monkeypatch):
    spec = importlib.util.spec_from_file_location('two_step_fixture', Path(__file__).with_name('test_pdf2md_enhanced_bad_text_policy.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    processor = fixture.page_processor
    tools = importlib.import_module(fixture.PACKAGE_NAME + '.single_page_tools')
    calls = []
    def describe(ctx, figures, blocks, vlm, counts, warnings):
        calls.append([figure['layout_id'] for figure in figures])
        counts['vlm_ocr'] += 1
        return [{**figure, 'description': 'figure description'} for figure in figures]
    monkeypatch.setattr(tools, '_enhance_layout_figures_with_vlm', describe)
    original = processor.process_page
    def two_steps(source_path, page_no, policy, vlm_config, routing_config, prev_context):
        first = original(source_path, page_no, policy, vlm_config,
                         {**routing_config, 'docs_recovery_phase': 'recognize'}, prev_context)
        assert calls == []
        assert first['decision']['glm_calls'] == 1
        ids = [x['layout_id'] for x in first['rag']['elements']['figures']]
        second = original(source_path, page_no, policy, vlm_config,
                          {**routing_config, 'docs_recovery_phase': 'recover',
                           '__docs_saved_layout': first['_docs_raw_layout'],
                           'docs_recovery_selection': {'figures': ids}}, prev_context)
        assert second['decision']['glm_calls'] == 0
        assert len(fixture.LayoutLedgerGLMOcrClient.calls) == 1
        return second
    monkeypatch.setattr(processor, 'process_page', two_steps)
    raw = fixture._layout_raw([
        {'index': 1, 'label': 'image', 'bbox_2d': [10, 10, 45, 70], 'content': ''},
        {'index': 2, 'label': 'image', 'bbox_2d': [55, 10, 90, 70], 'content': ''},
    ])
    result = fixture._run_layout_ledger_page(monkeypatch, raw, recovered={'tables': [], 'formulas': [], 'figures': []})
    assert len(calls) == 1 and len(calls[0]) == 2
    assert all(item.get('description') == 'figure description' for item in result['rag']['elements']['figures'])


def test_two_step_only_recovers_requested_tables_and_images(monkeypatch):
    spec = importlib.util.spec_from_file_location('two_step_table_fixture', Path(__file__).with_name('test_pdf2md_enhanced_bad_text_policy.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    processor = fixture.page_processor
    operations = []
    def recover(image, directory, payloads, vlm, enabled, max_objects, **kwargs):
        operations.append([item['layout_id'] for item in payloads['tables']])
        return 0, 0, {'pending': len(payloads['tables']), 'attempted': 0, 'objects': []}
    monkeypatch.setattr(processor, '_recover_missing_table_images', recover)
    original = processor.process_page
    def two_steps(source_path, page_no, policy, vlm_config, routing_config, prev_context):
        first = original(source_path, page_no, policy, vlm_config,
                         {**routing_config, 'docs_recovery_phase': 'recognize'}, prev_context)
        assert operations == []
        ids = [item['layout_id'] for item in first['rag']['elements']['tables']]
        assert len(ids) == 2
        second = original(source_path, page_no, policy, vlm_config,
                          {**routing_config, 'docs_recovery_phase': 'recover',
                           '__docs_saved_layout': first['_docs_raw_layout'],
                           'docs_recovery_selection': {'table_images': [ids[0]]}}, prev_context)
        assert second['decision']['glm_calls'] == 0
        assert len(fixture.LayoutLedgerGLMOcrClient.calls) == 1
        return second
    monkeypatch.setattr(processor, 'process_page', two_steps)
    table = '<table><tr><td>A</td></tr></table>'
    raw = fixture._layout_raw([
        {'index': 1, 'label': 'table', 'bbox_2d': [10, 10, 90, 40], 'content': table},
        {'index': 2, 'label': 'table', 'bbox_2d': [10, 50, 90, 80], 'content': table},
    ])
    result = fixture._run_layout_ledger_page(monkeypatch, raw, recovered={'tables': [], 'formulas': [], 'figures': []}, recovery_max_objects=2)
    assert operations == [[result['rag']['elements']['tables'][0]['layout_id']]]
    assert len(result['rag']['elements']['tables']) == 2


def test_two_step_table_recovery_uses_requested_provider_order(monkeypatch):
    spec = importlib.util.spec_from_file_location('two_step_provider_fixture', Path(__file__).with_name('test_pdf2md_enhanced_bad_text_policy.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    processor = fixture.page_processor
    plans = []
    def recover(*args, **kwargs):
        plans.append((kwargs.get('provider_plan'), kwargs.get('max_model_calls')))
        return 0, 0, {'objects': [], 'pending': 1, 'attempted': 0}
    monkeypatch.setattr(processor, '_recover_layout_objects', recover)
    original = processor.process_page
    def two_steps(source_path, page_no, policy, vlm_config, routing_config, prev_context):
        first = original(source_path, page_no, policy, vlm_config,
                         {**routing_config, 'docs_recovery_phase': 'recognize'}, prev_context)
        assert not plans
        return original(source_path, page_no, policy, vlm_config,
                        {**routing_config, 'docs_recovery_phase': 'recover',
                         '__docs_saved_layout': first['_docs_raw_layout'],
                         'docs_recovery_selection': {'tables': ['p1-o001-table'],
                           'table_provider_plan': ['glm_ocr'], 'table_model_budget': 1}}, prev_context)
    monkeypatch.setattr(processor, 'process_page', two_steps)
    raw = fixture._layout_raw([{'label': 'table', 'bbox_2d': [10, 20, 90, 90],
                                'content': '<table><tr><td>incomplete'}])
    fixture._run_layout_ledger_page(monkeypatch, raw, recovered={'tables': [], 'formulas': [], 'figures': []}, recovery_max_objects=1)
    assert plans == [(['glm_ocr'], 1)]


def test_recovery_does_not_add_unrequested_provider_attempts(monkeypatch, tmp_path):
    calls = []
    class OCR:
        enabled = True
        def extract_table_html(self, path):
            calls.append('glm_ocr')
            return '<table><tr><td>incomplete'
    class VLM:
        enabled = True
        def extract_table_html(self, *args, **kwargs):
            calls.append('vlm_ocr')
            raise AssertionError('VLM was not requested')
    monkeypatch.setattr(page_processor, '_crop_layout_block_image',
                        lambda *args, **kwargs: (tmp_path / 'crop.png', {'width': 20, 'height': 20}))
    block = {'layout_id': 'p1-o001-table', 'type': 'table', 'bbox': [.1, .1, .9, .9],
             'recovery_target': 'table_content_with_cell_images'}
    outcome = {'layout': [], 'payloads': {'tables': [], 'figures': [], 'formulas': []}}
    _, _, diagnostic = page_processor._recover_layout_objects(
        tmp_path / 'page.png', tmp_path, outcome, [block], VLM(), True, 1, 0,
        glm=OCR(), max_model_calls=3, provider_plan=['glm_ocr'])
    assert calls == ['glm_ocr']
    assert [attempt['provider'] for attempt in diagnostic['objects'][0]['attempts']] == ['glm_ocr']


def test_subsequent_recovery_preserves_previously_recovered_table(monkeypatch):
    spec = importlib.util.spec_from_file_location('subsequent_recovery_fixture', Path(__file__).with_name('test_pdf2md_enhanced_bad_text_policy.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    processor = fixture.page_processor
    def recover(image, directory, payloads, vlm, enabled, max_objects, **kwargs):
        for item in payloads['tables']:
            item['cell_image_inspection_status'] = 'complete'
            item['image_unresolved'] = []
        return 0, 0, {'pending': len(payloads['tables']), 'attempted': len(payloads['tables']), 'objects': []}
    monkeypatch.setattr(processor, '_recover_missing_table_images', recover)
    original = processor.process_page
    def recovery_rounds(source_path, page_no, policy, vlm_config, routing_config, prev_context):
        first = original(source_path, page_no, policy, vlm_config,
                         {**routing_config, 'docs_recovery_phase': 'recognize'}, prev_context)
        ids = [item['layout_id'] for item in first['rag']['elements']['tables']]
        assert len(ids) == 2
        def request(state, target):
            return original(source_path, page_no, policy, vlm_config,
                {**routing_config, 'docs_recovery_phase': 'recover', '__docs_saved_layout': state,
                 'docs_recovery_selection': {'table_images': [target], 'image_provider_plan': ['vlm_ocr'],
                                             'image_model_budget': 1}}, prev_context)
        second = request(first['_docs_raw_layout'], ids[0])
        import json
        json.dumps(second['_docs_raw_layout'])
        third = request(second['_docs_raw_layout'], ids[1])
        third.pop('_docs_raw_layout', None)
        return third
    monkeypatch.setattr(processor, 'process_page', recovery_rounds)
    table = '<table><tr><td>A</td></tr></table>'
    raw = fixture._layout_raw([{'label': 'table', 'bbox_2d': [10, 10, 90, 40], 'content': table},
                               {'label': 'table', 'bbox_2d': [10, 50, 90, 80], 'content': table}])
    result = fixture._run_layout_ledger_page(monkeypatch, raw, recovered={'tables': [], 'formulas': [], 'figures': []}, recovery_max_objects=2)
    assert [item.get('cell_image_inspection_status') for item in result['rag']['elements']['tables']] == ['complete', 'complete']
    assert len(fixture.LayoutLedgerGLMOcrClient.calls) == 1


def test_successful_image_round_clears_only_its_resolved_layout_review(monkeypatch):
    spec = importlib.util.spec_from_file_location('resolved_review_fixture', Path(__file__).with_name('test_pdf2md_enhanced_bad_text_policy.py'))
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    processor = fixture.page_processor
    def recover(image, directory, payloads, vlm, enabled, max_objects, **kwargs):
        for item in payloads['tables']:
            item.update(cell_image_inspection_status='complete', image_unresolved=[], manualReviewRequired=False)
        return 0, 0, {'objects': [{'layout_id': item['layout_id'], 'outcome': 'recovered'} for item in payloads['tables']]}
    monkeypatch.setattr(processor, '_recover_missing_table_images', recover)
    original = processor.process_page
    def rounds(source_path, page_no, policy, vlm_config, routing_config, prev_context):
        first = original(source_path, page_no, policy, vlm_config, {**routing_config, 'docs_recovery_phase': 'recognize'}, prev_context)
        def request(state, selection):
            return original(source_path, page_no, policy, vlm_config,
                {**routing_config, 'docs_recovery_phase': 'recover', '__docs_saved_layout': state,
                 'docs_recovery_selection': selection}, prev_context)
        second = request(first['_docs_raw_layout'], {'tables': ['p1-o001-table'], 'table_provider_plan': ['glm_ocr'], 'table_model_budget': 1})
        assert second['layout'][0]['status'] == 'EXTRACTED'
        third = request(second['_docs_raw_layout'], {'table_images': ['p1-o001-table'], 'image_provider_plan': ['vlm_ocr'], 'image_model_budget': 1})
        third.pop('_docs_raw_layout', None)
        return third
    monkeypatch.setattr(processor, 'process_page', rounds)
    incomplete = '<table><tr><td>unfinished'
    raw = fixture._layout_raw([{'label': 'table', 'bbox_2d': [10, 10, 90, 90], 'content': incomplete}])
    result = fixture._run_layout_ledger_page(monkeypatch, raw, recovery_max_objects=1,
                                            crop_results=['<table><tr><td>complete</td></tr></table>'])
    assert result['layout'][0]['review_required'] is False


def test_explicit_source_table_receives_image_inspection_without_repeat_ocr(monkeypatch):
    import json
    spec = importlib.util.spec_from_file_location('source_table_fixture', Path(__file__).with_name('test_pdf2md_enhanced_bad_text_policy.py'))
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    processor = fixture.page_processor
    raw = json.loads((Path(__file__).parent / 'fixtures' / 'asme_page23_calculation_text.json').read_text())
    body = raw['layout_details'][0][0]['content']
    seen = []
    def recover(image, directory, payloads, vlm, enabled, max_objects, **kwargs):
        seen.extend(payloads['tables'])
        return 0, 0, {'objects': []}
    monkeypatch.setattr(processor, '_recover_missing_table_images', recover)
    original = processor.process_page
    def rounds(source_path, page_no, policy, vlm_config, routing_config, prev_context):
        first = original(source_path, page_no, policy, vlm_config, {**routing_config, 'docs_recovery_phase': 'recognize'}, prev_context)
        layout_id = first['layout'][0]['layout_id']
        assert first['layout'][0]['type'] == 'text'
        source = {'layout_id': layout_id}
        second = original(source_path, page_no, policy, vlm_config,
            {**routing_config, 'docs_recovery_phase': 'recover', '__docs_saved_layout': first['_docs_raw_layout'],
             'docs_recovery_selection': {'source_tables': [source], 'table_images': [layout_id],
                 'image_provider_plan': ['vlm_ocr'], 'image_model_budget': 1}}, prev_context)
        assert second['decision']['glm_calls'] == 0
        second.pop('_docs_raw_layout', None)
        return second
    monkeypatch.setattr(processor, 'process_page', rounds)
    result = fixture._run_layout_ledger_page(monkeypatch, raw, recovered={'tables': [], 'formulas': [], 'figures': []}, recovery_max_objects=1)
    assert len(seen) == 1 and seen[0]['markdown'] == body
    assert result['rag']['elements']['tables'][0]['markdown'] == body
    assert result['layout'][0]['layout_id'] == seen[0]['layout_id']
    assert len(fixture.LayoutLedgerGLMOcrClient.calls) == 1


def test_source_table_binding_rejects_unknown_identity():
    import json
    import pytest
    ledger = importlib.import_module(package.__name__ + '.layout_ledger')
    raw = json.loads((Path(__file__).parent / 'fixtures' / 'asme_page23_calculation_text.json').read_text())
    outcome = ledger.build_layout_outcome(raw, 23, 1000, 1000)
    original = outcome['layout'][0]['content']
    with pytest.raises(ValueError, match='source_table_layout_mismatch'):
        page_processor._bind_requested_source_tables(outcome, [{'layout_id': 'other-object'}])
    assert outcome['layout'][0]['type'] == 'text'
    assert outcome['layout'][0]['content'] == original
    assert outcome['payloads']['tables'] == []


def test_text_source_image_without_cell_structure_stays_explicitly_unresolved():
    import json
    raw = json.loads((Path(__file__).parent / 'fixtures' / 'asme_page23_calculation_text.json').read_text())
    body = raw['layout_details'][0][0]['content']
    block = {'layout_id': 'p23-o001-text', 'type': 'table', 'markdown': body}
    candidate = {'layout_id': 'p23-o001-text', 'type': 'table', 'status': 'EXTRACTED',
                 'complete': True, 'contains_images': True, 'source_cells': [
                     {'row': 0, 'col': 0, 'bbox': [.1, .1, .9, .9], 'bbox_space': 'normalized_crop',
                      'image_regions': [{'image_id': 'diagram', 'bbox': [.2, .2, .8, .8],
                                         'bbox_space': 'normalized_crop'}]}]}
    reason, result = page_processor._validate_cell_image_recovery(block, candidate, {}, Path('/unused'))
    assert reason == 'table_structure_unavailable'
    assert result is None


def test_source_table_binding_uses_its_own_block_when_indices_are_missing():
    ledger = importlib.import_module(package.__name__ + '.layout_ledger')
    raw = {'data_info': {'width': 100, 'height': 100}, 'layout_details': [[
        {'label': 'text', 'bbox_2d': [0, 0, 40, 40], 'content': 'first',
         'source_cells': [{'row': 0, 'col': 0, 'text': 'wrong'}]},
        {'label': 'text', 'bbox_2d': [50, 50, 90, 90], 'content': 'second',
         'source_cells': [{'row': 0, 'col': 0, 'text': 'correct'}]},
    ]]}
    outcome = ledger.build_layout_outcome(raw, 1, 100, 100)
    page_processor._bind_requested_source_tables(outcome, [{'layout_id': 'p1-o002-text'}])
    assert outcome['payloads']['tables'][0]['source_cells'][0]['text'] == 'correct'
