"""Full-upload semantic contract; all model calls are fixtures."""
import copy

import pytest

from tests.test_pdf2md_enhanced_bad_text_policy import (
    page_processor as pp, LayoutLedgerVLMClient, _run_layout_ledger_page, _layout_raw,
)

HTML = '<table><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>'


def build(collection, payload, markdown=''):
    return pp._build_layout_output_elements(markdown, {collection: [payload]}, 'full_glm_ocr', 'zh')[collection][0]


@pytest.mark.parametrize('collection,payload,name_key,name,description,expected_status,missing', [
    ('tables', {'markdown': HTML}, 'title', '表 1 适用性', '比较不同介质的适用条件。', 'complete', []),
    ('tables', {'markdown': HTML}, 'title', '表 1 适用性', '表 1 适用性：比较不同介质。', 'complete', []),
    ('tables', {'markdown': HTML}, 'title', '表 1 适用性', '包含 0 行、0 列。', 'name_only', ['description']),
    ('tables', {'markdown': HTML}, 'title', '', '比较不同介质。', 'complete', ['title']),
    ('formulas', {'latex': 'F=ma', 'formula_no': '(3)'}, 'formula_name', '牛顿第二定律', '表示力与质量和加速度的关系。', 'complete', []),
    ('formulas', {'latex': 'F=ma'}, 'formula_name', '牛顿第二定律', '请结合上下文解释', 'name_only', ['description']),
    ('formulas', {'latex': 'F=ma', 'formula_no': '(3)'}, 'formula_name', '(3)', '(3)', 'missing', ['formula_name', 'description']),
    ('formulas', {'latex': 'F=ma'}, 'formula_name', '', '变量说明见原文', 'missing', ['formula_name', 'description']),
])
def test_upload_semantic_contract(collection, payload, name_key, name, description, expected_status, missing):
    obj = build(collection, {**payload, name_key: name, 'description': description})
    assert obj['semantic_status'] == expected_status
    assert obj['missing_fields'] == missing
    if expected_status == 'complete':
        assert obj['description'] == description
        if name:
            assert obj['semantic_summary'].count(name) == 1
        if payload.get('formula_no'):
            assert '(3)' in obj['semantic_summary']
    else:
        assert obj['description'] == ''
        assert obj['semantic_summary'] == (name if expected_status == 'name_only' else '')
    if collection == 'tables':
        assert obj['markdown'] == HTML
        assert '0 行' not in obj['semantic_summary']


def test_no_page_wide_name_or_variables_borrowing():
    markdown = '表 1 其他表格\n式中：x 是另一个公式的变量\n'
    table = build('tables', {'markdown': HTML}, markdown)
    formula = build('formulas', {'latex': 'F=ma'}, markdown)
    assert table['title'] == ''
    assert formula['variables'] == ''
    assert formula['context'] == ''


@pytest.mark.parametrize('score,source,expected', [(0.18, 'vlm_ocr', 0.18), (None, None, None), (0.9, None, None), (1.3, 'vlm_ocr', None)])
def test_semantic_confidence_is_independent(score, source, expected):
    item = build('tables', {'markdown': HTML, 'description': '比较介质。', 'confidence': 0.99,
                            'semantic_confidence': score, 'semantic_confidence_source': source})
    assert item['confidence'] == 0.99
    assert item.get('semantic_confidence') == expected


@pytest.mark.parametrize('failure', [False, True])
def test_layout_ocr_success_gets_one_semantic_pass_and_no_postrepair(monkeypatch, failure):
    calls = []
    def semantic(self, image_path, semantic_objects=None):
        calls.append(copy.deepcopy(semantic_objects))
        assert [o['object_ref'] for o in semantic_objects] == ['tables:0', 'tables:1']
        assert all(o['markdown'] == HTML for o in semantic_objects)
        assert len({o['layout_id'] for o in semantic_objects}) == 2
        if failure:
            raise RuntimeError('mock semantic failure')
        return {'tables': [
            {'object_ref': 'tables:1', 'title': '表 2 乙', 'description': '乙介质用途。', 'markdown': 'WRONG', 'confidence': 0.01},
            {'object_ref': 'tables:0', 'title': '表 1 甲', 'description': '甲介质用途。', 'semantic_confidence': 0.2,
             'semantic_confidence_source': 'vlm_ocr'},
        ]}
    monkeypatch.setattr(LayoutLedgerVLMClient, 'extract_region_structured', semantic, raising=False)
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {'index': 10, 'label': 'table', 'bbox_2d': [10, 10, 90, 40], 'content': HTML},
        {'index': 20, 'label': 'table', 'bbox_2d': [10, 60, 90, 90], 'content': HTML},
    ], markdown=HTML + '\n' + HTML), recovered={})
    assert len(calls) == 1
    assert result['decision']['vlm_calls'] == 1
    assert result['reconciliation']['complete'] is True
    tables = result['elements']['tables']
    assert [t['markdown'] for t in tables] == [HTML, HTML]
    assert len({t['layout_id'] for t in tables}) == 2
    if failure:
        assert [t['semantic_status'] for t in tables] == ['missing', 'missing']
        issues = result['semantic_status']['objects']
        assert [i['layout_id'] for i in issues] == [t['layout_id'] for t in tables]
        assert all(i['missing_fields'] == ['title', 'description'] for i in issues)
    else:
        assert [t['title'] for t in tables] == ['表 1 甲', '表 2 乙']
        assert [t['description'] for t in tables] == ['甲介质用途。', '乙介质用途。']
        assert tables[0]['semantic_confidence'] == 0.2
        assert tables[1].get('confidence') != 0.01


def test_figure_output_unchanged():
    figure = build('figures', {'caption': '图 1', 'description': '阀门连接储罐。', 'layout_id': 'p1-f', 'confidence': 0.8})
    assert figure['semantic_summary'] == '阀门连接储罐。'
    assert figure['caption'] == '图 1'
    assert figure['confidence'] == 0.8
    assert 'semantic_status' not in figure
    assert 'missing_fields' not in figure


@pytest.mark.parametrize('response', [
    {'tables': [{'object_ref': 'tables:0', 'title': '错误', 'description': '错误描述。', 'layout_id': 'wrong'}]},
    {'tables': [{'object_ref': 'tables:0', 'description': '重复一。'}, {'object_ref': 'tables:0', 'description': '重复二。'}]},
    {'formulas': [{'object_ref': 'tables:0', 'description': '跨类型。'}]},
    {'tables': [{'description': '没有引用。'}]},
])
def test_ambiguous_semantic_binding_fails_closed(response):
    payloads = {'tables': [{'layout_id': 'p1-table', 'markdown': HTML, 'title': '表 1 原名', 'confidence': 0.99}]}
    class VLM:
        def extract_region_structured(self, image_path, semantic_objects=None):
            return response
    assert pp._enrich_upload_semantics(VLM(), 'mock.png', {}, payloads, True) == 1
    table = build('tables', payloads['tables'][0])
    assert table['title'] == '表 1 原名'
    assert table['semantic_status'] == 'name_only'
    assert table['missing_fields'] == ['description']
    assert table['confidence'] == 0.99


def test_vlm_prompt_has_object_structure_names_and_own_context(monkeypatch):
    from tests.test_pdf2md_enhanced_object_recovery import VLMClient
    client = VLMClient({'enabled': True, 'model': 'mock', 'description_language': 'zh'})
    requests = []
    def call(image_path, prompt, max_tokens):
        requests.append(prompt)
        return '{"formulas":[]}'
    monkeypatch.setattr(client, '_call_image_prompt', call)
    client.extract_region_structured('mock-page.png', semantic_objects=[{
        'object_ref': 'formulas:0', 'latex': 'F=ma', 'formula_name': '牛顿第二定律',
        'formula_no': '(3)', 'variables': 'm 为质量', 'context': '物体所受合力',
    }])
    assert len(requests) == 1
    for text in ('F=ma', '牛顿第二定律', 'm 为质量', '物体所受合力', 'object_ref', 'another object', 'semantic_confidence'):
        assert text in requests[0]


@pytest.mark.parametrize('description', ['Formula: see the source document for variable definitions.', '公式（3）', '牛顿第二定律 (3)'])
def test_formula_number_or_named_number_is_not_description(description):
    item = build('formulas', {'latex': 'F=ma', 'formula_name': '牛顿第二定律', 'formula_no': '(3)', 'description': description})
    assert item['semantic_status'] == 'name_only'
    assert item['missing_fields'] == ['description']


def test_render_projection_keeps_known_html_and_semantics():
    pipe = '| D | E |\n| --- | --- |\n| 1 | 2 |'
    assert pp._select_rag_tables(pipe, [HTML, pipe]) == [HTML, pipe]
    assert pp._select_rag_tables('[TABLE_PLACEHOLDER] generated display', [HTML]) == [HTML]


def test_glm_fallback_failure_does_not_start_semantic_retry(monkeypatch):
    from tests import test_pdf2md_enhanced_bad_text_policy as f
    text = 'Formula F=ma and table measurements with sufficient embedded explanatory text. ' * 3
    page = f.FakePage(text, [(0, 0, 100, 20, text, 0, 0)])
    f._patch_page_runtime(monkeypatch, page)
    f.FakeGLMOcrClient.result = f.OcrResult(markdown='Fixture OCR text', tables=[
        f.OcrElement(kind='table', source='glm_ocr', markdown=HTML, title='表 1 原名')])
    calls = []
    monkeypatch.setattr(pp, '_structured_insufficient_for_route', lambda *args: True)
    def dual(self, image_path):
        calls.append('dual')
        raise ValueError('mock VLM failed')
    def semantic(self, image_path, semantic_objects=None):
        calls.append('semantic')
        return {}
    monkeypatch.setattr(f.FakeVLMClient, 'full_page_dual_output', dual)
    monkeypatch.setattr(f.FakeVLMClient, 'extract_region_structured', semantic)
    result = pp.process_page('/tmp/mock.pdf', 1, 'auto', {'enabled': True}, {
        'layout_ledger_enabled': False, 'render_cleanup_with_llm': False,
        'ocr_config': {'glm_ocr': {'enabled': True}},
    }, None)
    assert calls == ['dual']
    assert result['elements']['tables'][0]['semantic_status'] == 'name_only'


def test_recovered_formula_gets_normal_text_semantic_step():
    payload = {'formulas': [{'layout_id': 'p1-formula', 'latex': 'F=ma', 'description': 'crop description'}]}
    calls = []
    class VLM:
        def describe_formulas_text(self, page_text, formulas):
            calls.append('text')
            return {'formulas': [{'object_ref': 'formulas:0', 'description': '力等于质量乘加速度。'}]}
        def extract_region_structured(self, *args, **kwargs):
            pytest.fail('successful text semantics must not need an image')
    assert pp._enrich_upload_semantics(VLM(), 'mock.png', {}, payload, True, page_text='OCR body') == 1
    assert calls == ['text']
    assert payload['formulas'][0]['description'] == '力等于质量乘加速度。'


def test_formula_crop_and_layout_preserve_original_name_and_semantic_confidence():
    from tests.test_pdf2md_enhanced_object_recovery import ledger
    block = {'type': 'formula', 'layout_id': 'p1-formula'}
    payload = pp._object_success_payload(block, {
        'latex': 'F=ma', 'formula_name': '牛顿第二定律', 'formula_no': '(3)',
        'description': '力与质量和加速度的关系。', 'semantic_confidence': 0.25,
        'semantic_confidence_source': 'vlm_ocr', 'confidence': 0.99,
    })
    assert payload['formula_name'] == '牛顿第二定律'
    assert payload['semantic_confidence'] == 0.25
    outcome = ledger.build_layout_outcome(_layout_raw([
        {'label': 'formula', 'bbox_2d': [10, 20, 90, 40], 'content': 'F=ma',
         'formula_name': '牛顿第二定律', 'formula_no': '(3)'}
    ]), 1, 100, 100)
    assert outcome['payloads']['formulas'][0]['formula_name'] == '牛顿第二定律'


def test_table_context_does_not_borrow_from_same_named_other_object():
    table = build('tables', {'markdown': HTML, 'title': '表 1 对照', 'layout_id': 'p1-second'},
                  '另一个对象的专属解释\n表 1 对照\n')
    assert table['context'] == ''


def test_layout_structure_failure_keeps_field_level_object_reference(monkeypatch):
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {'index': 8, 'label': 'table', 'bbox_2d': [10, 20, 90, 40], 'content': ''},
    ]))
    assert result['elements']['tables'] == []
    issue = result['semantic_status']['objects'][0]
    assert issue['layout_id'] == result['layout'][0]['layout_id']
    assert issue['missing_fields'] == ['markdown', 'title', 'description']
    assert issue['index'] is None


def test_disabled_vlm_keeps_ocr_name_but_does_not_claim_ocr_semantics():
    structured = pp._normalize_structured({'tables': [{'markdown': HTML, 'title': '表 1 原名',
                                                       'description': 'OCR 自带说明。', 'confidence': 0.98}]})
    assert pp._enrich_upload_semantics(object(), 'mock.png', structured, None, False) == 0
    item = pp._build_output_elements('', structured, 'full_glm_ocr')['tables'][0]
    assert item['title'] == '表 1 原名'
    assert item['semantic_status'] == 'name_only'
    assert item['missing_fields'] == ['description']
    assert item['confidence'] == 0.98


def test_ocr_number_only_does_not_block_vlm_formula_name():
    structured = pp._normalize_structured({'formulas': [{'latex': 'F=ma', 'formula_name': '(3)'}]})
    class VLM:
        def describe_formulas_text(self, page_text, semantic_objects):
            return {'formulas': [{'object_ref': 'formulas:0', 'formula_name': '牛顿第二定律',
                                  'description': '合力等于质量乘加速度。'}]}
    pp._enrich_upload_semantics(VLM(), 'mock.png', structured, None, True)
    formula = pp._build_output_elements('', structured, 'full_glm_ocr')['formulas'][0]
    assert formula['formula_name'] == '牛顿第二定律'
    assert formula['formula_no'] == '(3)'


@pytest.mark.parametrize('route', ['hybrid_glm_ocr', 'full_glm_ocr'])
def test_both_ocr_routes_preserve_latex_and_pass_own_metadata(monkeypatch, route):
    from tests import test_pdf2md_enhanced_bad_text_policy as f
    page = f.FakePage('source text', [(0, 0, 100, 20, 'source text', 0, 0)])
    f._patch_page_runtime(monkeypatch, page)
    original = pp._decide_capability_route
    def routing(*args):
        result = original(*args)
        result.update(route_selected=route, mode='REGION_VLM' if route.startswith('hybrid') else 'FULL_VLM')
        return result
    monkeypatch.setattr(pp, '_decide_capability_route', routing)
    f.FakeGLMOcrClient.result = f.OcrResult(markdown='OCR body text', formulas=[
        f.OcrElement(kind='formula', source='glm_ocr', latex='F=ma', title='牛顿第二定律',
                     context='物体受到的合力', raw={'variables': 'm 是质量', 'confidence': 0.97})])
    calls = []
    def semantics(self, page_text, semantic_objects):
        calls.append(semantic_objects)
        assert semantic_objects[0]['formula_name'] == '牛顿第二定律'
        assert semantic_objects[0]['context'] == '物体受到的合力'
        assert semantic_objects[0]['variables'] == 'm 是质量'
        return {'formulas': [{'object_ref': 'formulas:0', 'latex': 'WRONG', 'description': '合力与加速度成正比。',
                              'semantic_confidence': 0.15, 'semantic_confidence_source': 'vlm_ocr'}]}
    monkeypatch.setattr(f.FakeVLMClient, 'describe_formulas_text', semantics, raising=False)
    result = pp.process_page('/tmp/mock.pdf', 1, 'auto', {}, {
        'layout_ledger_enabled': False, 'render_cleanup_with_llm': False,
        'ocr_config': {'glm_ocr': {'enabled': True}},
    }, None)
    assert len(calls) == 1
    formula = result['elements']['formulas'][0]
    assert formula['latex'] == 'F=ma'
    assert formula['confidence'] == 0.97
    assert formula['semantic_confidence'] == 0.15
    assert formula['semantic_status'] == 'complete'


@pytest.mark.parametrize('number', ['(A.1)', '式（A-2）', 'Equation (3a)', '(IV)'])
def test_appendix_and_subformula_numbers_are_not_names_or_descriptions(number):
    formula = build('formulas', {'latex': 'F=ma', 'formula_name': number, 'description': number})
    assert formula['semantic_status'] == 'missing'
    assert formula['missing_fields'] == ['formula_name', 'description']
    assert formula['formula_no'] == number


@pytest.mark.parametrize('text_result', ['valid', 'empty', 'placeholder', 'error', 'duplicate', 'wrong_id'])
def test_formula_text_first_image_fallback_is_bounded_and_targeted(text_result):
    payloads = {'formulas': [
        {'layout_id': 'p1-f1', 'latex': 'F=ma', 'formula_name': '牛顿第二定律', 'confidence': 0.98},
        {'layout_id': 'p1-f2', 'latex': 'E=mc^2'},
    ]}
    calls = []
    class VLM:
        def describe_formulas_text(self, page_text, formulas):
            calls.append(('text', [f['object_ref'] for f in formulas]))
            assert 'm 为质量' in page_text
            first = {'object_ref': 'formulas:0', 'layout_id': 'p1-f1', 'description': '力等于质量乘加速度。',
                     'semantic_confidence': 0.2, 'semantic_confidence_source': 'vlm_ocr'}
            if text_result == 'error':
                raise RuntimeError('mock text failure')
            second = {'object_ref': 'formulas:1', 'description': '表达质量与能量的关系。'}
            if text_result == 'placeholder':
                second['description'] = '请结合上下文解释'
            if text_result == 'wrong_id':
                second['layout_id'] = 'foreign'
            return {'formulas': [first] + ([] if text_result == 'empty' else [second, second] if text_result == 'duplicate' else [second])}
        def extract_region_structured(self, image_path, semantic_objects=None):
            refs = [f['object_ref'] for f in semantic_objects]
            calls.append(('image', refs))
            assert refs == (['formulas:0', 'formulas:1'] if text_result == 'error' else ['formulas:1'])
            return {'formulas': [{'object_ref': ref, 'description': '根据原文解释物理量之间的关系。',
                                  'latex': 'WRONG', 'confidence': 0.01} for ref in refs]}
    count = pp._enrich_upload_semantics(VLM(), 'mock-page.png', {}, payloads, True, page_text='F=ma。式中 m 为质量。E=mc^2。')
    assert calls[0] == ('text', ['formulas:0', 'formulas:1'])
    assert count == len(calls) == (1 if text_result == 'valid' else 2)
    result = pp._build_layout_output_elements('', payloads, 'full_glm_ocr')['formulas']
    assert [f['latex'] for f in result] == ['F=ma', 'E=mc^2']
    assert all(f['semantic_status'] == 'complete' for f in result)
    assert result[0]['confidence'] == 0.98
    if text_result != 'error':
        assert result[0]['description'] == '力等于质量乘加速度。'
        assert result[0]['semantic_confidence'] == 0.2


def test_formula_text_and_image_failure_stop_with_missing_fields():
    calls = []
    class VLM:
        def describe_formulas_text(self, page_text, formulas):
            calls.append('text')
            return {'formulas': [{'object_ref': 'formulas:0', 'formula_name': '牛顿第二定律', 'description': '变量说明见原文'}]}
        def extract_region_structured(self, image_path, semantic_objects=None):
            calls.append('image')
            return {}
    payload = {'formulas': [{'layout_id': 'p1-f1', 'latex': 'F=ma'}]}
    assert pp._enrich_upload_semantics(VLM(), 'mock.png', {}, payload, True, page_text='OCR body') == 2
    item = build('formulas', payload['formulas'][0])
    assert calls == ['text', 'image']
    assert item['semantic_status'] == 'name_only'
    assert item['missing_fields'] == ['description']


@pytest.mark.parametrize('label,content', [
    ('inline_formula', r'$p=10$'), ('formula', r'$p$'), ('formula', r'\sigma_{s}'),
    ('formula', '式中 p 为设计压力，D 为内径。'), ('formula', r'$p$ — 设计压力，MPa'),
    ('formula', r'p: design pressure, MPa'),
])
def test_variable_explanations_stay_in_layout_text(label, content):
    from tests.test_pdf2md_enhanced_object_recovery import ledger
    raw = _layout_raw([
        {'label': 'formula', 'bbox_2d': [10, 10, 90, 30], 'content': 'F=ma'},
        {'label': label, 'bbox_2d': [10, 40, 90, 60], 'content': content},
        {'label': 'formula', 'bbox_2d': [10, 70, 90, 90], 'content': 'E=mc^2'},
    ], markdown='')
    outcome = ledger.build_layout_outcome(raw, 1, 100, 100)
    assert [f['latex'] for f in outcome['payloads']['formulas']] == ['F=ma', 'E=mc^2']
    assert outcome['layout'][1]['type'] == 'text'
    assert content in outcome['markdown']
    assert [f['layout_id'] for f in outcome['payloads']['formulas']] == ['p1-o001-formula', 'p1-o003-formula']


def test_formula_text_chat_has_no_image_and_preserves_identity(monkeypatch):
    from tests.test_pdf2md_enhanced_object_recovery import VLMClient
    client = VLMClient({'model': 'mock', 'api_key': 'unused', 'base_url': 'http://127.0.0.1:1', 'max_retries': 0})
    calls = []
    def wire(**kwargs):
        content = kwargs['messages'][0]['content']
        calls.append(content)
        assert all(c['type'] == 'text' for c in content)
        assert 'p1-f1' in content[0]['text'] and 'm 为质量' in content[0]['text']
        return '{"formulas":[{"object_ref":"formulas:0","description":"解释力与加速度关系。"}]}', 'stream', 'stop'
    monkeypatch.setattr(client, '_chat_completion_with_stream_fallback', wire)
    result = client.describe_formulas_text('式中 m 为质量', [{'object_ref': 'formulas:0', 'layout_id': 'p1-f1', 'latex': 'F=ma'}])
    assert len(calls) == 1
    assert result['formulas'][0]['object_ref'] == 'formulas:0'


def test_crop_latex_only_formula_is_sent_as_text_with_page_body(monkeypatch):
    calls = []
    def text(self, page_text, formulas):
        assert 'm 为质量' in page_text
        assert [f['layout_id'] for f in formulas] == ['p1-o002-formula']
        calls.append('text')
        return {'formulas': [{'object_ref': 'formulas:0', 'description': '力等于质量乘加速度。'}]}
    def image(self, image_path, semantic_objects=None):
        pytest.fail('text succeeded; no image semantic call expected')
    monkeypatch.setattr(LayoutLedgerVLMClient, 'describe_formulas_text', text, raising=False)
    monkeypatch.setattr(LayoutLedgerVLMClient, 'extract_region_structured', image, raising=False)
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {'label': 'text', 'bbox_2d': [10, 10, 90, 20], 'content': '式中 m 为质量'},
        {'label': 'formula', 'bbox_2d': [10, 30, 90, 50], 'content': ''},
    ], markdown='式中 m 为质量'), recovered={'formulas': [{'layout_id': 'p1-o002-formula', 'latex': 'F=ma'}]})
    assert calls == ['text']
    assert result['decision']['formula_semantic_calls'] == {'text': 1, 'image': 0}
    assert result['elements']['formulas'][0]['description'] == '力等于质量乘加速度。'
    assert result['elements']['formulas'][0]['source'] == 'glm_ocr_layout+vlm_object_crop'


@pytest.mark.parametrize('layout', [True, False])
def test_body_latex_survives_upload_without_formula_object(monkeypatch, layout):
    from tests import test_pdf2md_enhanced_bad_text_policy as f
    body = [r'$p$', '式中 p 为设计压力。']
    if layout:
        result = _run_layout_ledger_page(monkeypatch, _layout_raw([
            {'label': 'formula', 'bbox_2d': [10, 10+i*30, 90, 30+i*30], 'content': value}
            for i, value in enumerate(body)
        ], markdown='OCR introduction'))
    else:
        page = f.FakePage('Source body', [(0, 0, 100, 20, 'Source body', 0, 0)])
        f._patch_page_runtime(monkeypatch, page)
        f.FakeGLMOcrClient.result = f.OcrResult(markdown='OCR introduction', formulas=[
            f.OcrElement(kind='formula', source='glm_ocr', latex=value) for value in body])
        result = pp.process_page('/tmp/mock.pdf', 1, 'auto', {}, {
            'layout_ledger_enabled': False, 'render_cleanup_with_llm': False,
            'ocr_config': {'glm_ocr': {'enabled': True}},
        }, None)
    assert result['elements']['formulas'] == []
    for value in body:
        assert value in result['render']['markdown']
        assert value in result['rag']['page_text']
        assert value in result['rag']['content']
    assert result['decision']['formula_semantic_calls'] == {'text': 0, 'image': 0}


def test_recovered_variable_atom_is_body_text_without_reconciliation_failure(monkeypatch):
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {'label': 'formula', 'bbox_2d': [10, 20, 90, 50], 'content': ''},
    ], markdown='OCR body'), recovered={'formulas': [{'layout_id': 'p1-o001-formula', 'latex': r'$p$'}]})
    assert result['elements']['formulas'] == []
    assert result['layout'][0]['type'] == 'text'
    assert result['layout'][0]['layout_id'] == 'p1-o001-formula'
    assert result['reconciliation']['complete'] is True
    assert r'$p$' in result['rag']['page_text']


def test_text_semantics_receives_ocr_markdown_when_page_text_is_partial(monkeypatch):
    from tests import test_pdf2md_enhanced_bad_text_policy as f
    page = f.FakePage('Body', [(0, 0, 100, 20, 'Body', 0, 0)])
    f._patch_page_runtime(monkeypatch, page)
    f.FakeGLMOcrClient.result = f.OcrResult(markdown='F=ma。式中 m 为质量', page_text='Chapter 1', formulas=[
        f.OcrElement(kind='formula', source='glm_ocr', latex='F=ma')])
    texts = []
    def text(self, page_text, formulas):
        texts.append(page_text)
        return {'formulas': [{'object_ref': 'formulas:0', 'description': '合力与加速度的关系。'}]}
    monkeypatch.setattr(f.FakeVLMClient, 'describe_formulas_text', text, raising=False)
    pp.process_page('/tmp/mock.pdf', 1, 'auto', {}, {
        'layout_ledger_enabled': False, 'render_cleanup_with_llm': False,
        'ocr_config': {'glm_ocr': {'enabled': True}},
    }, None)
    assert len(texts) == 1
    assert 'Chapter 1' in texts[0] and 'm 为质量' in texts[0]


@pytest.mark.parametrize('content', [r'\mathrm{MPa}', r'\Delta p', r'$\sigma$——许用应力'])
def test_latex_units_and_variable_notation_are_body_text(content):
    from tests.test_pdf2md_enhanced_object_recovery import ledger
    assert ledger.is_formula_body_text(content) is True


@pytest.mark.parametrize('content', [r'F=ma', r'\Delta p=\rho g h', r'\frac{a+b}{c}', r'\int_0^1 f(x) dx'])
def test_main_equations_and_expressions_are_not_demoted(content):
    from tests.test_pdf2md_enhanced_object_recovery import ledger
    assert ledger.is_formula_body_text(content) is False


def test_formula_image_fallback_cannot_overwrite_text_success():
    payload = {'formulas': [{'latex': 'F=ma'}, {'latex': 'E=mc^2'}]}
    class VLM:
        def describe_formulas_text(self, page_text, formulas):
            return {'formulas': [{'object_ref': 'formulas:0', 'description': '合力与加速度的关系。'}]}
        def extract_region_structured(self, image_path, semantic_objects=None):
            assert [t['object_ref'] for t in semantic_objects] == ['formulas:1']
            return {'formulas': [
                {'object_ref': 'formulas:0', 'description': '错误覆盖。'},
                {'object_ref': 'formulas:1', 'description': '质量与能量的关系。'},
            ]}
    pp._enrich_upload_semantics(VLM(), 'mock.png', {}, payload, True)
    assert payload['formulas'][0]['description'] == '合力与加速度的关系。'
    assert payload['formulas'][1]['description'] == '质量与能量的关系。'


def numbered_layout(contents, markdown='', extra=()):
    blocks = [{'label': 'formula', 'content': text, 'bbox_2d': [100, 100+i*100, 600, 150+i*100]}
              for i, text in enumerate(contents)]
    raw = _layout_raw(blocks + list(extra), markdown)
    raw['data_info'] = {'width': 1000, 'height': 1000}
    return pp.build_layout_outcome(raw, 1, 1000, 1000)


@pytest.mark.parametrize('text', [r'$$x=y \tag{B-9}$$', r'$$x=y \quad (\text{B-9})$$', '$x=y$ （B-9）'])
def test_formula_number_from_math_not_only_metadata(text):
    result = numbered_layout([text])
    assert result['payloads']['formulas'][0]['formula_no'] == 'B-9'
    assert result['payloads']['formulas'][0]['latex'] == text


def test_formula_numbers_from_whole_page_markdown_bind_by_content():
    result = numbered_layout(['$$x=y$$', '$$a=b$$'], '$$a=b \\quad (\\text{B-10})$$\n$x=y$ （B-9）')
    assert [f['formula_no'] for f in result['payloads']['formulas']] == ['B-9', 'B-10']


def test_formula_number_from_unique_right_hand_block():
    result = numbered_layout(['$$x=y$$'], extra=[{'label': 'text', 'content': '（B-19）', 'bbox_2d': [800, 100, 900, 150]}])
    assert result['payloads']['formulas'][0]['formula_no'] == 'B-19'
    assert len(result['layout']) == 2


@pytest.mark.parametrize('contents,markdown', [
    (['$$x=y$$'], '按公式（B-9）计算\n$$x=y$$'),
    (['$$x=y$$', '$$x=y$$'], '$$x=y \\tag{B-9}$$'),
    (['$$x=y$$'], '$$x=y \\tag{B-9}$$\n$$x=y \\tag{B-10}$$'),
])
def test_formula_number_does_not_guess_from_references_or_duplicates(contents, markdown):
    result = numbered_layout(contents, markdown)
    assert all(not f['formula_no'] for f in result['payloads']['formulas'])


def test_numbered_page_eight_and_thirteen_keep_identity_and_output_contract():
    formulas = ['R=(T_1-T_2)/(t_2-t_1)', 'T_m=0.4T_1+0.6T_2',
                't_m=0.4t_1+0.6t_2', r'T_m=\frac{1}{2}(T_1+T_2)',
                r't_m=\frac{1}{2}(t_1+t_2)', 't_h=T_m-Kr_h', 't_c=t_m+Kr_c',
                r't_t=\frac{1}{2}(t_h+t_c)']
    # Same-page Markdown in a different order must still bind by formula content.
    markdown = '\n'.join('$$' + f + r' \quad (\text{B-' + str(i+8) + '})$$'
                         for i, f in reversed(list(enumerate(formulas))))
    outcome = numbered_layout(['$$'+f+'$$' for f in formulas], markdown)
    output = pp._build_layout_output_elements(markdown, outcome['payloads'], 'full_glm_ocr', 'zh')['formulas']
    assert [f['formula_no'] for f in output] == ['B-'+str(i) for i in range(8, 16)]
    assert [f['latex'] for f in output] == ['$$'+f+'$$' for f in formulas]
    assert [f['layout_id'] for f in output] == [f'p1-o{i:03d}-formula' for i in range(1, 9)]
    other = numbered_layout(['$$w_i=a/b$$', '$$p=x+y$$', '$$EEI=K/p$$'],
                            '$$w_i=a/b$$ (B-18)\n$$p=x+y$$ (B-19)\n$$EEI=K/p$$ (B-20)')
    assert [f['formula_no'] for f in other['payloads']['formulas']] == ['B-18', 'B-19', 'B-20']


def test_ambiguous_right_number_does_not_bind_and_figure_is_unchanged():
    extra = [{'label': 'text', 'content': '(B-9)', 'bbox_2d': [800, 100, 900, 250]},
             {'label': 'figure', 'content': 'figure content', 'bbox_2d': [100, 700, 600, 800]}]
    result = numbered_layout(['$$x=y$$', '$$a=b$$'], extra=extra)
    assert all(not f['formula_no'] for f in result['payloads']['formulas'])
    assert result['payloads']['figures'][0]['description'] == 'figure content'


@pytest.mark.parametrize('latex', ['$$x=(1)$$', '$$x = (1)$$', '$$x=y+(2)$$'])
def test_parenthesized_operand_is_not_formula_number(latex):
    assert not numbered_layout([latex])['payloads']['formulas'][0]['formula_no']


def test_number_ocr_recovers_only_unique_geometry_once(tmp_path):
    import fitz
    image = tmp_path / 'page.png'
    doc = fitz.open(); page = doc.new_page(width=1000, height=1000)
    page.get_pixmap().save(str(image)); doc.close()
    formulas = [{'layout_id': 'a', 'bbox': [.1,.1,.6,.15], 'latex': 'x=y', 'description': 'keep'},
                {'layout_id': 'b', 'bbox': [.1,.3,.6,.35], 'latex': 'a=b', 'formula_no': 'B-2'}]
    class OCR:
        supports_number_ocr = True
        calls = 0
        def extract_number_lines(self, path):
            assert path == str(image)
            self.calls += 1
            return {'status': 'succeeded', 'words_result': [
                {'words': '…………(B-1)', 'location': {'left':800,'top':100,'width':100,'height':50}},
                {'words': '按公式(B-9)计算', 'location': {'left':100,'top':80,'width':500,'height':20}},
                {'words': 'a=b……(B-99)', 'location': {'left':100,'top':300,'width':800,'height':50}}]}
    client = OCR()
    stats = pp._recover_formula_numbers(client, str(image), formulas)
    assert client.calls == 1
    assert formulas[0] == {'layout_id':'a','bbox':[.1,.1,.6,.15],'latex':'x=y','description':'keep','formula_no':'B-1'}
    assert formulas[1]['formula_no'] == 'B-2'
    assert stats['calls'] == 1 and stats['missing_objects'] == []
    assert pp._recover_formula_numbers(client, str(image), formulas)['calls'] == 0
    assert client.calls == 1


def test_number_ocr_actual_page_eight_response(monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    data = json.loads((Path(__file__).parent/'fixtures/pdf2md_formula_number_page8.json').read_text())
    formulas = data['formulas']; before = copy.deepcopy(formulas)
    monkeypatch.setattr(pp.fitz, 'Pixmap', lambda _: SimpleNamespace(width=1820,height=2573))
    ocr = SimpleNamespace(supports_number_ocr=True, extract_number_lines=lambda _: data['ocr'])
    stats = pp._recover_formula_numbers(ocr, 'whole-page.png', formulas)
    assert [f['formula_no'] for f in formulas] == [f'B-{i}' for i in range(8,16)]
    assert stats['calls'] == 1 and stats['missing_objects'] == []
    assert [{k:v for k,v in f.items() if k != 'formula_no'} for f in formulas] == before


def test_number_ocr_failure_does_not_lose_formulas(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(pp.fitz, 'Pixmap', lambda _: SimpleNamespace(width=100,height=100))
    def fail(_): raise TimeoutError()
    formulas = [{'layout_id':'f1','latex':'x=y','bbox':[.1,.1,.6,.2]}]
    before = copy.deepcopy(formulas)
    stats = pp._recover_formula_numbers(SimpleNamespace(supports_number_ocr=True,extract_number_lines=fail), 'page', formulas)
    assert formulas == before
    assert stats == {'calls':1,'status':'failed','error_type':'TimeoutError',
                     'missing_objects':[{'layout_id':'f1','missing_fields':['formula_no']}]}


def test_number_ocr_is_wired_into_upload_once(monkeypatch):
    from types import SimpleNamespace
    from tests.test_pdf2md_enhanced_bad_text_policy import LayoutLedgerGLMOcrClient
    calls = []
    monkeypatch.setattr(LayoutLedgerGLMOcrClient, 'supports_number_ocr', True, raising=False)
    def extract(self, path):
        calls.append(path)
        return {'status':'succeeded','words_result':[{'words':'……(B-19)',
            'location':{'left':80,'top':10,'width':15,'height':10}}]}
    monkeypatch.setattr(LayoutLedgerGLMOcrClient, 'extract_number_lines', extract, raising=False)
    monkeypatch.setattr(pp.fitz, 'Pixmap', lambda _: SimpleNamespace(width=100,height=100))
    result = _run_layout_ledger_page(monkeypatch, _layout_raw([
        {'label':'formula','content':'$$x=y$$','bbox_2d':[10,10,60,20]}]))
    assert calls == ['/tmp/layout-page.png']
    assert result['elements']['formulas'][0]['formula_no'] == 'B-19'
    assert result['rag']['elements']['formulas'][0]['formula_no'] == 'B-19'
    assert result['decision']['formula_number_ocr']['calls'] == 1


def test_number_ocr_transport_full_image_one_request(monkeypatch, tmp_path):
    import io
    import urllib.request
    image = tmp_path/'page.png'; image.write_bytes(b'whole-image-bytes')
    client = pp.OpenAICompatibleOcrClient({'enabled':True,'model':'glm-ocr',
        'base_url':'https://open.bigmodel.cn/api/paas/v4','api_key':'fixture','max_retries':5})
    calls = []
    def post(request, timeout):
        calls.append(request)
        assert request.full_url == 'https://open.bigmodel.cn/api/paas/v4/files/ocr'
        assert b'whole-image-bytes' in request.data and b'hand_write' in request.data
        return io.BytesIO(b'{"status":"succeeded","words_result":[]}')
    monkeypatch.setattr(urllib.request, 'urlopen', post)
    assert client.extract_number_lines(str(image))['status'] == 'succeeded'
    assert len(calls) == 1
    def fail(request, timeout):
        calls.append(request); raise TimeoutError()
    monkeypatch.setattr(urllib.request, 'urlopen', fail)
    with pytest.raises(TimeoutError): client.extract_number_lines(str(image))
    assert len(calls) == 2  # no transport retry despite max_retries=5


def test_number_ocr_ambiguous_line_is_not_assigned(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(pp.fitz,'Pixmap',lambda _:SimpleNamespace(width=100,height=100))
    formulas = [{'layout_id':str(i),'latex':'x=y','bbox':[.1,.1,.6,.2]} for i in range(2)]
    ocr = SimpleNamespace(supports_number_ocr=True,extract_number_lines=lambda _: {
        'status':'succeeded','words_result':[{'words':'……(B-19)','location':{'left':80,'top':10,'width':15,'height':10}}]})
    stats = pp._recover_formula_numbers(ocr,'page',formulas)
    assert len(stats['missing_objects']) == 2
    assert all(not f.get('formula_no') for f in formulas)


@pytest.mark.parametrize("heading,value", [("Experiment", "Microscope"), ("Product", "Assembly"), ("项目", "趋势图")])
def test_layout_table_preserves_supplied_cell_geometry_across_content_domains(heading, value):
    html = f'<table><tr><th>{heading}</th><th>Image</th></tr><tr><td>{value}</td><td></td></tr></table>'
    cells = [{"row": 1, "col": 1, "rowspan": 1, "colspan": 1, "text": "",
              "bbox": [0.5, 0.4, 0.9, 0.7], "bbox_space": "normalized_page", "confidence": 0.98}]
    raw = _layout_raw([{"index": 1, "label": "table", "bbox_2d": [10, 20, 90, 70],
                        "content": html, "source_cells": cells, "source_cell_row_offset": 1}])
    before = copy.deepcopy(raw)
    outcome = pp.build_layout_outcome(raw, 1, 100, 100)
    table = pp._build_layout_output_elements(html, outcome["payloads"], "full_glm_ocr", "en")["tables"][0]
    assert table["source_cells"] == cells
    assert table["source_cell_row_offset"] == 1
    assert table["markdown"] == html
    assert table["layout_id"] == "p1-o001-table"
    assert raw == before



def test_geometry_only_figures_survive_without_claiming_semantic_success():
    outcome = pp.build_layout_outcome(_layout_raw([
        {"index": 1, "label": "figure", "bbox_2d": [10, 10, 40, 40], "content": ""},
        {"index": 2, "label": "figure", "bbox_2d": [50, 10, 90, 40], "content": ""},
        {"index": 3, "label": "figure", "content": ""},
    ]), 1, 100, 100)
    before = copy.deepcopy(outcome)
    elements = pp._build_layout_output_elements("", outcome["payloads"], "full_glm_ocr", "en")
    assert len(elements["figures"]) == 2
    assert [f["layout_id"] for f in elements["figures"]] == ["p1-o001-figure", "p1-o002-figure"]
    assert all(f["description"] == "" and f["semantic_status"] == "missing" for f in elements["figures"])
    assert all(f["content_status"] == "geometry_only" for f in elements["figures"])
    assert outcome == before
    result = pp.reconcile_layout(outcome["layout_status"], outcome["layout"], elements)
    assert result["accounted_for"] is True
    assert result["complete"] is False
    assert result["failed"] == 3
    assert len(pp.recovery_blocks(outcome)) == 2
    assert outcome["layout"][0]["payload_ref"] == {"collection": "figures", "index": 0}


def test_recovered_figure_replaces_only_its_geometry_placeholder():
    outcome = pp.build_layout_outcome(_layout_raw([
        {"index": 1, "label": "figure", "bbox_2d": [10, 10, 40, 40], "content": ""},
        {"index": 2, "label": "figure", "bbox_2d": [50, 10, 90, 40], "content": ""},
    ]), 1, 100, 100)
    pp.apply_recovered_payloads(outcome, {"figures": [{"layout_id": "p1-o001-figure",
        "description": "A microscope arrangement with a light source.", "content_status": "geometry_only"}]})
    elements = pp._build_layout_output_elements("", outcome["payloads"], "full_glm_ocr", "en")
    assert len(elements["figures"]) == 2
    assert elements["figures"][0]["description"] == "A microscope arrangement with a light source."
    assert "content_status" not in elements["figures"][0]
    assert elements["figures"][1]["content_status"] == "geometry_only"
    result = pp.reconcile_layout(outcome["layout_status"], outcome["layout"], elements)
    assert result["accounted_for"] is True
    assert result["extracted"] == 1
    assert result["failed"] == 1
    assert result["duplicate_layout_ids"] == []


@pytest.mark.parametrize("corruption", ["bbox", "duplicate", "semantic_status"])
def test_geometry_only_reconciliation_rejects_mismatched_payload(corruption):
    outcome = pp.build_layout_outcome(_layout_raw([
        {"index": 1, "label": "image", "bbox_2d": [10, 10, 40, 40], "content": ""},
    ]), 1, 100, 100)
    elements = pp._build_layout_output_elements("", outcome["payloads"], "full_glm_ocr", "en")
    if corruption == "duplicate":
        elements["figures"].append(copy.deepcopy(elements["figures"][0]))
    elif corruption == "bbox":
        elements["figures"][0]["bbox"] = [0.5, 0.5, 0.9, 0.9]
    else:
        elements["figures"][0]["semantic_status"] = "complete"
    result = pp.reconcile_layout(outcome["layout_status"], outcome["layout"], elements)
    assert result["accounted_for"] is False
    assert result["complete"] is False
