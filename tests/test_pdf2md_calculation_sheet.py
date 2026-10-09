"""Calculation sheets: source-bound offline contracts, no providers."""
import copy
import importlib
import json

import pytest
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools as sp
from tests.test_pdf2md_enhanced_upload_semantics import pp

cs = importlib.import_module(sp.__package__ + '.calculation_sheet')
HTML = '<table><tr><td rowspan="14">Inputs</td><td>Pressure p MPa</td></tr><tr><td>Calculation</td><td>Force $F=pA$ N</td></tr><tr><td>Check</td><td>When p&gt;0, F&lt;10</td></tr></table>'


@pytest.fixture
def calculation_image(tmp_path):
    import fitz
    path = tmp_path / 'calculation.png'
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
    image.clear_with(255)
    image.save(path)
    return str(path)


CALCULATION_REGION = {'bbox': [0, 0, 1, 1], 'bbox_space': 'normalized_page'}


@pytest.mark.parametrize('patch,reason', [
    ({'table_kind': 'invalid'}, 'classification_kind_invalid'),
    ({'classification_evidence': []}, 'classification_evidence_missing'),
    ({'classification_evidence': ['foreign']}, 'classification_evidence_mismatch'),
    ({'table_kind': 'uncertain'}, 'classification_model_uncertain'),
])
def test_classification_diagnostics_distinguish_model_and_validation(patch, reason):
    candidate = proposal(); candidate.update(patch); item = {}
    cs.apply_calculation_sheet(item, candidate, HTML)
    assert item['table_classification']['reason'] == reason
    assert item['table_classification']['proposed_kind'] == candidate['table_kind']


def test_ambiguous_classification_quote_has_own_diagnostic():
    item = {}
    cs.apply_calculation_sheet(item, {'table_kind': 'calculation_sheet',
                                    'classification_evidence': ['p']}, 'p p')
    assert item['table_classification']['reason'] == 'classification_evidence_ambiguous'


def test_legacy_classification_is_not_reported_as_success():
    item = {}
    cs.apply_calculation_sheet(item, {}, 'Pressure')
    assert item['table_kind'] == 'data_table'
    assert item['table_classification']['reason'] == 'classification_not_run'


def test_organize_existing_rpc_honors_manual_type_without_reading_images(monkeypatch):
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / 'fixtures/calculation_processing_contract.json').read_text())
    class VLM:
        enabled = True
        table_analysis_max_model_calls = 2
        last_call_info = {}
        def extract_calculation_sheet(self, image_path, target):
            assert image_path is None
            assert target['processing_mode'] == 'organize_existing'
            return copy.deepcopy(fixture['provider_response'])
    monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: VLM())
    monkeypatch.setattr(sp, '_prepare_context', lambda *a, **k: pytest.fail('organize must not read an image'))
    result = json.loads(sp.extract_page_tables_direct(**fixture['request']))
    assert result['status'] == 'needs_review'
    assert result['table_kind'] == 'calculation_sheet'
    assert result['table_kind_source'] == 'manual'
    assert result['calculation_identity'] == fixture['request']['context']['calculation_request']['identity']
    assert result['calculation_sheet']['image_verified'] is False
    assert result['calculation_sheet']['sections'][0]['items'][0]['content'] == 'Pressure p = MPa'
    assert result['model_calls']['vlm_ocr'] == 1
    assert result == {k: v for k, v in fixture['mcp_response'].items() if k not in ('items', 'tables')}


def proposal(content=HTML):
    return {'table_kind': 'calculation_sheet', 'classification_evidence': ['Force $F=pA$ N'],
            'calculation_sheet': {'sections': [
                {'title': 'Inputs', 'items': [
                    {'kind': 'input', 'name': 'Pressure', 'sources': ['Inputs', 'Pressure p MPa'], 'unit': 'MPa'}]},
                {'title': 'Calculation', 'items': [
                    {'kind': 'formula', 'name': 'Force', 'sources': ['Calculation', 'Force $F=pA$ N'], 'latex': 'F=pA', 'unit': 'N'},
                    {'kind': 'check', 'name': 'Check', 'sources': ['Check', 'When p>0, F<10'], 'conditions': ['When p>0'], 'checks': ['F<10']}]}],
                'unresolved': [], 'image_discrepancies': []}}


def test_calculation_sheet_bypasses_grid_preserves_source_and_conditions(monkeypatch):
    monkeypatch.setattr(sp, '_html_table_to_grid', lambda *_: pytest.fail('not a data grid'))
    item = {'markdown': HTML, 'layout_id': 'p1-t1', 'bbox': [0, 0, 1, 1]}
    original = copy.deepcopy(item)
    cs.apply_calculation_sheet(item, proposal(), HTML)
    assert item['markdown'] == original['markdown']
    sheet = item['calculation_sheet']
    assert sheet['validation_status'] == 'source_validated'
    assert sheet['quality_status'] == 'needs_review'
    assert sheet['image_verified'] is False
    assert sheet['sections'][1]['items'][1]['conditions'] == ['When p>0']
    assert '$F=pA$' in sheet['render_markdown']
    assert item['lookup_sections'] == []
    out = pp._build_layout_output_elements('', {'tables': [item]}, 'full_glm_ocr')['tables'][0]
    assert out['calculation_sheet'] == sheet
    assert 'contained_formula_quality' not in out


@pytest.mark.parametrize('mutation,reason', [
    (lambda p: p['calculation_sheet']['sections'][1]['items'][0].update(latex='F=p/A'), 'formula_source_mismatch'),
    (lambda p: p['calculation_sheet']['sections'].pop(), 'unmapped_source_text'),
    (lambda p: p['calculation_sheet']['sections'][1]['items'][1].update(conditions=['When p<0']), 'field_source_mismatch'),
    (lambda p: p['calculation_sheet']['sections'][0]['items'][0].update(sources=['not in this object']), 'invalid_source_reference'),
])
def test_rejects_omissions_and_rewrites(mutation, reason):
    p = proposal(); mutation(p); item = {'markdown': HTML}
    cs.apply_calculation_sheet(item, p, HTML)
    assert item['calculation_sheet']['validation_status'] == 'unresolved'
    assert reason in [x['reason'] for x in item['calculation_sheet']['unresolved']]


@pytest.mark.parametrize('kind', ['mixed', 'uncertain', 'unknown'])
def test_unsupported_type_defaults_to_data_table(kind):
    item = {'markdown': HTML}; p = proposal(); p['table_kind'] = kind
    cs.apply_calculation_sheet(item, p, HTML)
    assert item['table_kind'] == 'data_table'
    assert 'manualReviewRequired' not in item
    assert not item.get('calculation_sheet', {}).get('sections')


def test_data_table_unchanged():
    item = {'markdown': HTML}; cs.apply_calculation_sheet(item, {'table_kind':'data_table','classification_evidence':['Inputs']}, HTML)
    assert item['markdown'] == HTML
    assert 'calculation_sheet' not in item
    assert 'lookup_status' not in item


def framed_proposal(target):
    return {**target, 'sections': [{'title': section['title'], 'items': [
        {'source_item_id': unit['id'], 'kind': 'formula' if cs.math_content(unit['text']) else 'note',
         'latex': cs.math_content(unit['text'])[0] if cs.math_content(unit['text']) else '',
         'semantic_desc': 'Records the supplied calculation information for review.'}
        for unit in section['items']]} for section in target['source_sections']],
        'semantic_desc': 'Describes the source calculation and its inputs.',
        'unresolved': [], 'image_discrepancies': []}





def test_metadata_merge_single_page_and_query_guard():
    item = {'markdown': HTML, 'raw_html': HTML}
    sp._merge_table_metadata([item], [{'index':0, **proposal()}])
    assert 'table_kind' not in item and 'calculation_sheet' not in item
    from tests.test_pdf2md_enhanced_table_query import request
    q = importlib.import_module(sp.__package__ + '.table_query')
    req = request(HTML); req['table']['table_kind'] = 'calculation_sheet'
    result = q.enhance_table(req, lambda *_: pytest.fail('grid forbidden'), lambda *_: pytest.fail('provider forbidden'))
    assert result['query_enhancement']['model_calls'] == 0
    assert result['query_enhancement']['unresolved'][0]['reason'] == 'calculation_sheet_not_data_table'


def test_duplicate_metadata_identity_is_not_merged():
    item = {'markdown': HTML}
    sp._merge_table_metadata([item], [{'index':0, **proposal()}, {'index':0, **proposal()}])
    assert 'calculation_sheet' not in item


def test_direct_vlm_normalization_keeps_validated_not_raw_proposal():
    obj = {'markdown': HTML, **proposal()}
    out = pp._build_output_elements('', pp._normalize_structured({'tables':[obj]}), 'full_vlm_ocr')['tables'][0]
    assert out['calculation_sheet']['validation_status'] == 'source_validated'
    assert out['calculation_sheet']['quality_status'] == 'needs_review'


def test_single_page_glm_keeps_source_without_accepting_calculation_proposal(monkeypatch, calculation_image):
    from tests.test_pdf2md_enhanced_single_page_tools import (
        _patch_clients, FakeGLMOcrClient, FakeVLMClient, OcrResult, OcrElement, PNG_DATA)
    import base64
    from pathlib import Path
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(tables=[OcrElement(kind='table', source='glm_ocr', markdown=HTML, raw=dict(CALCULATION_REGION))])
    monkeypatch.setattr(FakeVLMClient, 'result_text', json.dumps({'tables':[{'index':0, **proposal()}]}))
    monkeypatch.setattr(FakeVLMClient, 'extract_calculation_sheet', lambda self, path, target: framed_proposal(target) if path is None else {**target, 'source_text': HTML}, raising=False)
    monkeypatch.setattr(FakeVLMClient, 'table_analysis_max_model_calls', 3, raising=False)
    out = json.loads(sp.extract_page_tables_direct(file_data=base64.b64encode(Path(calculation_image).read_bytes()).decode(), input_type='image',
        ocr_config={'glm_ocr': {'enabled':True, 'model':'stub', 'api_key':'stub', 'base_url':'http://stub'}},
        vlm_config={'model':'stub', 'api_key':'stub', 'base_url':'http://stub'}))
    assert out['model_calls'] == {'glm_ocr':1, 'vlm_ocr':1}
    assert 'table_kind' not in out
    assert out['raw_html'] == HTML
    assert '_pending_grid' not in out['tables'][0]
    assert 'calculation_sheet' not in out
    assert 'calculation_source' not in out


def test_single_page_vlm_does_not_adopt_calculation_json(monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import OcrElement
    raw = {'markdown':HTML, **proposal(), 'bbox':[.1,.1,.8,.8], 'bbox_space':'normalized_page'}
    item = sp._table_item('vlm_ocr', HTML, '', True, OcrElement(kind='table', source='vlm_ocr', markdown=HTML, raw=raw))
    assert 'calculation_sheet' not in item and 'table_kind' not in item
    assert item['bbox'] == raw['bbox']
    assert item['raw_html'] == HTML






def test_ambiguous_quote_and_image_discrepancies_require_review():
    p = proposal(); p['calculation_sheet']['image_discrepancies'] = [{'reason':'formula differs in image'}]
    item={}; cs.apply_calculation_sheet(item,p,HTML)
    assert 'image_ocr_discrepancy' in [x['reason'] for x in item['calculation_sheet']['unresolved']]
    with pytest.raises(ValueError): cs._quote_range('same same', 'same')


@pytest.mark.parametrize('value', [None, [], {}, {'sections':None}, {'sections':[None]}, {'sections':[{'title':'x','items':[{'kind':[]}]}]}])
def test_malformed_calculation_response_fails_closed(value):
    p=proposal();p['calculation_sheet']=value;item={};cs.apply_calculation_sheet(item,p,HTML)
    assert item['calculation_sheet']['validation_status'] == 'unresolved'
    assert item['manualReviewRequired'] is True


def test_no_title_only_classification_or_foreign_source():
    item={};p=proposal();p['classification_evidence']=['not in source']
    cs.apply_calculation_sheet(item,p,HTML)
    assert item['table_kind'] == 'data_table'


def test_render_escapes_markup_and_pipes():
    rendered=cs._render([{'title':'<script>','items':[{'name':'a|b','content':'x<script>\ny|z'}]}])
    assert '<script>' not in rendered
    assert 'a&#124;b' in rendered


def test_missing_items_and_generated_evidence_cannot_report_success():
    p = proposal();p.pop('calculation_sheet')
    item={};cs.apply_calculation_sheet(item,p,HTML)
    assert item['calculation_sheet']['validation_status'] == 'unresolved'
    p['classification_evidence']=['This worksheet calculates pressure.']
    item={};cs.apply_calculation_sheet(item,p,HTML)
    assert item['table_kind'] == 'data_table'




def test_table_prompt_requires_items_without_suppressing_them(monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import DynamicVLMClient
    client=DynamicVLMClient(None);client.description_language='en'
    prompts=[]
    monkeypatch.setattr(client,'_call_image_prompt',lambda path,prompt,**kw: prompts.append(prompt) or '{}')
    client.extract_region_structured('unused',[{'type':'table','object_ref':'tables:0','calculation_source':cs.source_context(HTML)}])
    assert 'REQUIRED in addition to semantic metadata' in prompts[0]
    assert 'do not extract or return replacement structure' not in prompts[0]
    assert 'a dedicated call handles them' in prompts[0]


def test_formula_syntax_and_branch_condition_are_checked():
    source='<table><tr><td>Force $F={pA$</td></tr></table>'
    candidate={'table_kind':'calculation_sheet','classification_evidence':['Force $F={pA$'],
               'calculation_sheet':{'sections':[{'title':'Calculation','items':[{'kind':'formula','name':'Force','sources':['Force $F={pA$'],'latex':'F={pA'}]}], 'unresolved':[], 'image_discrepancies':[]}}
    item={};cs.apply_calculation_sheet(item,candidate,source)
    assert {'reason':'formula_unbalanced'} in item['calculation_sheet']['unresolved']


def test_quality_does_not_equate_name_description_to_image_acceptance():
    assert cs.table_content_quality([{'table_kind':'calculation_sheet','semantic_status':'complete'}])['complete'] is False


@pytest.mark.parametrize('bbox', [[0,0,2,1], [.9,.9,.8,1], [False,0,1,1]])
def test_item_geometry_cannot_escape_source(bbox):
    p=proposal();p['calculation_sheet']['sections'][0]['items'][0]['bbox']=bbox
    item={'bbox':[0,0,1,1]};cs.apply_calculation_sheet(item,p,HTML)
    assert {'reason':'item_bbox_invalid'} in item['calculation_sheet']['unresolved']


def test_item_geometry_distinct_from_table_geometry():
    p=proposal();p['calculation_sheet']['sections'][0]['items'][0]['bbox']=[.1,.1,.3,.2]
    item={'bbox':[0,0,1,1]};cs.apply_calculation_sheet(item,p,HTML)
    source=item['calculation_sheet']['sections'][0]['items'][0]['source']
    assert source['bbox']==[.1,.1,.3,.2]
    assert source['location_scope']=='item'








@pytest.mark.parametrize('mode,reason', [('wrong_id','calculation_identity_mismatch'),('truncated','calculation_response_truncated'),('failure','calculation_provider_failed')])
def test_dedicated_parser_checks_identity_and_provider_failure(mode,reason, calculation_image):
    class VLM:
        last_call_info={'finish_reason':'length' if mode=='truncated' else 'stop'}
        def extract_calculation_sheet(self,path,target):
            if mode=='failure':raise RuntimeError('private provider details')
            return {'object_ref':'wrong' if mode=='wrong_id' else target['object_ref'],
                    'source_sha256':target['source_sha256'],**proposal()['calculation_sheet']}
    cp = importlib.import_module(cs.__package__ + '.calculation_processing')
    item = dict(CALCULATION_REGION)
    cp.structure_calculation_source(VLM(), item, HTML,
        {'object_ref': 'tables:0', 'source_sha256': cs.source_context(HTML)['sha256']}, 1)
    assert {'reason':reason} in item['calculation_sheet']['unresolved']
    assert item['calculation_sheet']['coverage']['represented'] > 0
    assert item['calculation_sheet']['coverage']['structured'] == 0
    assert 'private' not in json.dumps(item)



def test_dedicated_prompt_has_one_schema_and_no_metadata_only_instruction(monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import DynamicVLMClient
    client=DynamicVLMClient(None);prompts=[]
    monkeypatch.setattr(client,'_call_image_prompt',lambda path,prompt,**kw: prompts.append(prompt) or '{}')
    client.extract_calculation_sheet('unused',{'object_ref':'tables:0','source_sha256':'hash'})
    assert len(prompts)==1 and 'sections at TOP LEVEL' in prompts[0]
    assert 'classification_evidence' not in prompts[0]
    assert 'semantic metadata' not in prompts[0]


def test_generated_group_title_obeys_requested_language():
    p=proposal();p['calculation_sheet']['sections'][0]['title']='计算参数与输入条件说明'
    item={};cs.apply_calculation_sheet(item,p,HTML,'en')
    assert {'reason':'section_title_language_mismatch'} in item['calculation_sheet']['unresolved']


def test_chinese_two_column_labels():
    assert cs._render([], 'zh').startswith('| 项目／步骤 | 内容 |')


@pytest.mark.parametrize('formula', [r'$x<y$', r'$$S<S_a$$', r'\(x<y\)', r'\[S<S_a\]'])
def test_source_context_preserves_math_comparisons_inside_html(formula):
    content = '<table><tr><td>Criteria</td><td>' + formula + '</td></tr></table>'
    ctx = cs.source_context(content)
    assert formula in ctx['text']
    assert '<td>' not in ctx['text']


def test_rejected_calculation_item_retains_candidate_and_failed_field():
    p = proposal(); p['calculation_sheet']['sections'][1]['items'][0]['latex'] = 'F=p/A'
    item = {}
    cs.apply_calculation_sheet(item, p, HTML)
    sheet = item['calculation_sheet']
    rejected = sheet['rejected_items'][0]
    assert rejected['section_index'] == 1
    assert rejected['section_title'] == 'Calculation'
    assert rejected['item_index'] == 0
    assert rejected['field'] == 'latex'
    assert rejected['reason'] == 'formula_source_mismatch'
    assert rejected['candidate']['latex'] == 'F=p/A'
    assert all(x.get('latex') != 'F=p/A' for section in sheet['sections'] for x in section['items'])
    assert sheet['unmapped_ranges']
    assert sheet['validation_status'] == 'unresolved'


def test_descriptive_name_does_not_discard_source_verified_formula():
    candidate = proposal()
    entry = candidate['calculation_sheet']['sections'][1]['items'][0]
    entry.update(name='Calculated force', semantic_desc='Calculates force from pressure and loaded area.',
                 inputs=['p', 'A'], output='F')
    item = {}; cs.apply_calculation_sheet(item, candidate, HTML)
    sheet = item['calculation_sheet']
    formula = next(x for s in sheet['sections'] for x in s['items'] if x.get('latex') == 'F=pA')
    assert formula['name'] == 'F=pA'
    assert formula['semantic_desc'] == entry['semantic_desc']
    assert formula['inputs'] == ['p', 'A'] and formula['output'] == 'F'
    assert formula['rejected_fields'][0]['field'] == 'name'
    assert 'field_source_mismatch' in [x['reason'] for x in sheet['unresolved']]


def test_calculation_meaning_and_dependency_survive_without_inventing_values():
    text = 'Area A mm2\nForce F N\nStress $s=F/A$ MPa\nCheck $s<S$'
    raw = {'semantic_desc': 'Calculates stress and checks its allowable limit.', 'sections': [
        {'title': 'Stress verification', 'items': [
            {'kind': 'input', 'name': 'Area', 'symbol': 'A', 'unit': 'mm2', 'sources': ['Area A mm2']},
            {'kind': 'input', 'name': 'Force', 'symbol': 'F', 'unit': 'N', 'sources': ['Force F N']},
            {'kind': 'formula', 'name': 'Stress', 'latex': 's=F/A', 'sources': ['Stress $s=F/A$ MPa'],
             'semantic_desc': 'Calculates stress from force divided by area.', 'inputs': ['F', 'A'], 'output': 's'},
            {'kind': 'check', 'name': 'Check', 'checks': ['s<S'], 'sources': ['Check $s<S$'],
             'semantic_desc': 'Checks stress against the allowable stress.', 'inputs': ['s', 'S']}
        ]}], 'unresolved': [], 'image_discrepancies': []}
    sheet = cs.parse_calculation_sheet(raw, cs.source_context(text), {})
    assert sheet['semantic_desc'] == raw['semantic_desc']
    items = sheet['sections'][0]['items']
    assert items[2]['depends_on'] == [items[1]['id'], items[0]['id']]
    assert items[3]['depends_on'] == [items[2]['id']]
    assert items[3]['unresolved_inputs'] == ['S']
    assert 'value' not in items[0]
    assert sheet['image_verified'] is False


def test_missing_semantics_does_not_delete_an_equation():
    sheet = cs.parse_calculation_sheet(proposal()['calculation_sheet'], cs.source_context(HTML), {})
    formula = sheet['sections'][1]['items'][0]
    assert formula['latex'] == 'F=pA'
    assert formula['semantic_status'] == 'missing'


def test_foreign_dependency_symbol_is_rejected_without_losing_formula():
    raw = proposal()['calculation_sheet']; raw['sections'][1]['items'][0].update(inputs=['foreign'], output='F')
    sheet = cs.parse_calculation_sheet(raw, cs.source_context(HTML), {})
    formula = sheet['sections'][1]['items'][0]
    assert formula['latex'] == 'F=pA' and formula['inputs'] == []
    assert any(x['field'] == 'inputs' for x in formula['rejected_fields'])


def test_source_supported_steps_and_ambiguous_inputs_are_not_guessed():
    raw = proposal()['calculation_sheet']
    raw['steps'] = [{'title': 'Calculate force', 'semantic_desc': 'Use pressure and area to calculate force.',
                     'item_ids': ['item-2'], 'sources': ['Force $F=pA$ N']}]
    sheet = cs.parse_calculation_sheet(raw, cs.source_context(HTML), {})
    assert sheet['steps'][0]['item_ids'] == ['item-2']
    assert sheet['steps'][0]['source']['text_ranges']
    raw['steps'][0]['item_ids'] = ['other-page-item']
    rejected = cs.parse_calculation_sheet(raw, cs.source_context(HTML), {})
    assert rejected['steps'] == []
    assert rejected['rejected_steps'][0]['reason'] == 'calculation_step_reference_invalid'
    assert rejected['sections'][1]['items'][0]['latex'] == 'F=pA'


def test_explicit_source_ranges_disambiguate_repeated_formula_without_changing_it():
    text = 'First F=pA\nSecond F=pA'
    raw = {'sections': [{'title': 'Repeated equations', 'items': [
        {'kind': 'formula', 'name': 'F', 'latex': 'F=pA', 'sources': ['F=pA'], 'source_ranges': [[6, 10]]},
        {'kind': 'formula', 'name': 'F', 'latex': 'F=pA', 'sources': ['F=pA'], 'source_ranges': [[18, 22]]}
    ]}], 'unresolved': [], 'image_discrepancies': []}
    sheet = cs.parse_calculation_sheet(raw, cs.source_context(text), {})
    assert len(sheet['sections'][0]['items']) == 2
    assert sheet['sections'][0]['items'][1]['source']['text_ranges'] == [[18, 22]]
    raw['sections'][0]['items'][1]['source_ranges'] = [[17, 21]]
    assert len(cs.parse_calculation_sheet(raw, cs.source_context(text), {})['sections'][0]['items']) == 1

@pytest.mark.parametrize('opening,closing', [('$', '$'), ('$$', '$$'), (r'\(', r'\)'), (r'\[', r'\]')])
def test_framed_symbol_note_accepts_only_outer_math_delimiters(opening, closing):
    formula = r'S_{m}^{s}'
    quote = f'{opening}{formula}{closing} = membrane stress in the short side.'
    ctx = cs.source_context(quote)
    ctx['source_sections'] = []
    entry = {'kind': 'note', 'name': formula, 'latex': opening + formula + closing,
             'sources': [quote], 'output': '', 'inputs': [],
             'semantic_desc': 'Defines the short-side membrane stress symbol.'}
    sheet = cs._parse_calculation_sheet({'sections': [{'title': '', 'items': [entry]}]}, ctx, {})
    assert len(sheet['sections'][0]['items']) == 1
    item = sheet['sections'][0]['items'][0]
    assert item['latex'] == formula
    assert not item.get('rejected_fields')
    for altered in [r'S_{m}^{l}', r'S_{m}', r'S_{m}^{s}+1']:
        bad = {**entry, 'latex': opening + altered + closing}
        result = cs._parse_calculation_sheet({'sections': [{'title': '', 'items': [bad]}]}, ctx, {})
        assert not result['sections'][0]['items']


def test_empty_optional_output_is_not_a_source_error_but_foreign_output_is():
    ctx = cs.source_context('$F=pA$')
    entry = {'kind': 'formula', 'name': 'F', 'latex': 'F=pA', 'sources': ['$F=pA$'],
             'output': '', 'semantic_desc': 'Calculates force from pressure and area.'}
    sheet = cs._parse_calculation_sheet({'sections': [{'title': '', 'items': [entry]}]}, ctx, {})
    assert not sheet['sections'][0]['items'][0].get('rejected_fields')
    entry['output'] = 'foreign'
    sheet = cs._parse_calculation_sheet({'sections': [{'title': '', 'items': [entry]}]}, ctx, {})
    assert sheet['sections'][0]['items'][0]['rejected_fields'][0]['field'] == 'output'


@pytest.mark.parametrize('kind,formula', [('check', r'S_m+S_b\le 1.5S'), ('note', r'S_{bi}^{sB},S_{bo}^{sB}')])
def test_framed_math_selection_restores_exact_source_without_model_recopied_latex(kind, formula):
    ctx = cs.source_context('$' + formula + '$')
    ctx['source_sections'] = cs.calculation_source_sections(ctx['text'])
    assert ctx['source_sections'][0]['items'][0]['math'] == [formula]
    entry = {'source_item_id': 's1-i1', 'kind': kind, 'latex_source_index': 0,
             'semantic_desc': 'Explains the supplied source expression.'}
    raw = {'sections': [{'title': '', 'items': [entry]}]}
    sheet = cs.parse_calculation_sheet(raw, ctx, {})
    item = sheet['sections'][0]['items'][0]
    assert item['latex'] == formula
    if kind == 'check':
        assert item['checks'] == [formula]
    assert sheet['coverage']['structured'] == 1
    for bad in [-1, 1, True, '0']:
        entry['latex_source_index'] = bad
        rejected = cs.parse_calculation_sheet(raw, ctx, {})
        assert rejected['coverage']['structured'] == 0
    entry['latex_source_index'] = 0
    entry['latex'] = 'foreign'
    rejected = cs.parse_calculation_sheet(raw, ctx, {})
    assert rejected['coverage']['structured'] == 0


@pytest.mark.parametrize('kind,formula', [('formula', 'x=y+z'), ('check', 'x<y'), ('note', 'x_i,x_o')])
def test_framed_single_math_is_restored_without_redundant_model_index(kind, formula):
    ctx = cs.source_context('$' + formula + '$')
    ctx['source_sections'] = cs.calculation_source_sections(ctx['text'])
    raw = {'sections': [{'title': '', 'items': [{'source_item_id': 's1-i1', 'kind': kind,
           'semantic_desc': 'Explains this exact source relationship.'}]}]}
    sheet = cs.parse_calculation_sheet(raw, ctx, {})
    assert sheet['coverage']['structured'] == 1
    item = sheet['sections'][0]['items'][0]
    assert item['latex'] == formula
    if kind == 'check':
        assert item['checks'] == [formula]


def test_framed_text_note_accepts_no_math_selection_but_rejects_false_index():
    ctx = cs.source_context('Q means thermal energy.')
    ctx['source_sections'] = cs.calculation_source_sections(ctx['text'])
    entry = {'source_item_id': 's1-i1', 'kind': 'note', 'latex_source_index': None,
             'semantic_desc': 'Defines Q as thermal energy.'}
    raw = {'sections': [{'title': '', 'items': [entry]}]}
    assert cs.parse_calculation_sheet(raw, ctx, {})['coverage']['structured'] == 1
    for invalid in (-1, 0, '0', True):
        entry['latex_source_index'] = invalid
        assert cs.parse_calculation_sheet(raw, ctx, {})['coverage']['structured'] == 0


def test_explicit_text_only_heading_preserves_its_source_range_without_display_markers():
    text = '## Results\n$x=y$\n## Legend\nQ means thermal energy.'
    sections = cs.calculation_source_sections(text)
    assert [s['title'] for s in sections] == ['Results', 'Legend']
    assert [len(s['items']) for s in sections] == [1, 1]
    for section in sections:
        a, b = section['source_range']
        assert text[a:b] == '## ' + section['title']
    assert sections[1]['items'][0]['text'] == 'Q means thermal energy.'


def test_plain_heading_before_symbol_definition_is_a_section_not_a_note():
    text = 'Calculation\n$Q=mcT$\nLegend\nQ – thermal energy.'
    sections = cs.calculation_source_sections(text)
    assert [s['title'] for s in sections] == ['Calculation', 'Legend']
    assert [len(s['items']) for s in sections] == [1, 1]
    assert sections[1]['items'][0]['text'] == 'Q – thermal energy.'


def source_first_sheet(text, entry):
    ctx = cs.source_context(text)
    ctx['source_sections'] = cs.calculation_source_sections(ctx['text'])
    ctx['description_language'] = 'en'
    unit = ctx['source_sections'][0]['items'][0]
    raw = {'semantic_desc': 'Describes the supplied calculation expression and its applicability.',
           'sections': [{'title': '', 'items': [{'source_item_id': unit['id'], **entry}]}],
           'unresolved': [], 'image_discrepancies': []}
    return cs.parse_calculation_sheet(raw, ctx, {})


def test_source_first_optional_item_description_does_not_make_complete_formula_missing():
    sheet = source_first_sheet('$r=a/b$', {'kind': 'formula', 'latex_source_index': 0})
    assert sheet['sections'][0]['items'][0]['latex'] == 'r=a/b'
    assert sheet['coverage']['needs_review'] == 0
    assert sheet['semantic_status'] == 'model_proposed'


def test_source_first_second_math_in_condition_is_not_a_missing_main_formula():
    sheet = source_first_sheet('$r=2$ for identical members with $a=b$',
                               {'kind': 'formula', 'latex_source_index': 0,
                                'conditions': ['for identical members with $a=b$']})
    assert sheet['coverage']['needs_review'] == 0
    assert not any(issue['reason'] == 'formula_needs_completion' for issue in sheet['unresolved'])


def test_source_first_bad_auxiliary_field_keeps_formula_and_valid_conditions():
    sheet = source_first_sheet('$r=a/b$ for $b>0$',
                               {'kind': 'formula', 'latex_source_index': 0,
                                'conditions': ['for $b>0$', 'invented condition']})
    item = sheet['sections'][0]['items'][0]
    assert item['latex'] == 'r=a/b'
    assert item['conditions'] == ['for $b>0$']
    assert any(field['field'] == 'conditions' for field in item['rejected_fields'])
    assert sheet['coverage']['needs_review'] == 1







@pytest.mark.parametrize('kind', ['data_table', 'calculation_sheet'])
def test_missing_evidence_defaults_without_repair(kind):
    item = {'markdown': HTML, 'columns': ['A'], 'normalized_rows': [['1']]}
    cs.apply_calculation_sheet(item, {'table_kind': kind}, HTML)
    assert item['table_classification']['status'] == 'evidence_unresolved'
    class VLM:
        def classify_table(self, *args):
            pytest.fail('missing evidence must not trigger another model call')
    assert cs.repair_table_classification(VLM(), 'page.png', item, HTML, 'tables:0', 1) == 0
    assert item['table_kind'] == 'data_table'
    assert item['table_classification']['proposed_kind'] == kind
    assert item['columns'] == ['A'] and item['normalized_rows'] == [['1']]


def test_classification_repair_preserves_proposal_budget_and_manual_decision():
    item = {}
    cs.apply_calculation_sheet(item, {'table_kind': 'data_table'}, HTML)
    class VLM:
        last_call_info = {}
        calls = 0
        def classify_table(self, *_):
            self.calls += 1
            return {'table_kind': 'data_table'}
    vlm = VLM()
    assert cs.repair_table_classification(vlm, 'page.png', item, HTML, 'one', 0) == 0
    assert 'repair_reason' not in item['table_classification']
    assert cs.repair_table_classification(vlm, 'page.png', item, HTML, 'one', 1) == 0
    assert item['table_kind'] == 'data_table'
    assert item['table_classification']['proposed_kind'] == 'data_table'
    assert cs.repair_table_classification(vlm, 'page.png', item, HTML, 'one', 1) == 0
    manual = {'table_kind': 'calculation_sheet', 'table_kind_source': 'manual'}
    assert cs.repair_table_classification(vlm, 'page.png', manual, HTML, 'two', 1) == 0
    assert vlm.calls == 0


def test_semantically_uncertain_classification_is_not_format_retry():
    item = {}
    cs.apply_calculation_sheet(item, {'table_kind': 'uncertain', 'classification_evidence': ['Force $F=pA$ N']}, HTML)
    assert item['table_classification']['status'] == 'unresolved'
    assert cs.repair_table_classification(object(), 'page.png', item, HTML, 'one', 1) == 0




@pytest.mark.parametrize('response', [
    {'object_ref': 'other', 'table_kind': 'data_table', 'classification_evidence': ['Force $F=pA$ N']},
    {'table_kind': 'data_table', 'classification_evidence': ['foreign evidence']},
])
def test_repair_never_accepts_other_object_or_unbound_evidence(response):
    item = {}
    cs.apply_calculation_sheet(item, {'table_kind': 'data_table'}, HTML)
    class VLM:
        last_call_info = {}
        def classify_table(self, *_):
            return response
    assert cs.repair_table_classification(VLM(), 'page.png', item, HTML, 'this', 1) == 0
    assert item['table_kind'] == 'data_table'
    assert item['table_classification']['status'] == 'evidence_unresolved'


@pytest.mark.parametrize('title', ['管板应力计算表', 'Stress Calculation'])
def test_title_is_independent_source_evidence_without_changing_body(title):
    body = 'Parameter p'
    ctx = cs.source_context(body, evidence=True, source_title=title)
    base = cs.source_context(body, evidence=True)
    assert ctx['text'] == base['text'] and ctx['sha256'] == base['sha256']
    block = next(b for b in ctx['evidence_blocks'] if b.get('source_field') == 'title')
    item = {'title': title}
    cs.apply_calculation_sheet(item, {'table_kind': 'calculation_sheet',
        'classification_evidence': [{'block_id': block['id'], 'source_sha256': block['source_sha256']}]}, body)
    assert item['table_kind'] == 'calculation_sheet'
    assert item['table_classification']['evidence_status'] == 'located'
    assert item['table_classification']['evidence'][0]['source_field'] == 'title'
    other = {'title': 'Another table'}
    cs.apply_calculation_sheet(other, {'table_kind': 'calculation_sheet',
        'classification_evidence': [{'block_id': block['id'], 'source_sha256': block['source_sha256']}]}, body)
    assert other['table_classification']['reason'] == 'classification_evidence_mismatch'


def test_image_transcription_can_quote_current_title_but_not_generated_description():
    item = {'title': 'Stress Calculation', 'description': 'Generated formula summary'}
    cs.apply_calculation_sheet(item, {'table_kind': 'calculation_sheet',
        'classification_evidence': ['Stress Calculation']}, 'Parameter p')
    assert item['table_classification']['evidence_status'] == 'located'
    cs.apply_calculation_sheet(item, {'table_kind': 'calculation_sheet',
        'classification_evidence': ['Generated formula summary']}, 'Parameter p')
    assert item['table_classification']['reason'] == 'classification_evidence_mismatch'


@pytest.mark.parametrize('field', ['title', 'table_title'])
def test_new_image_title_can_be_cited_without_replacing_existing_title(field):
    candidate = {field: '应力计算表', 'table_kind': 'calculation_sheet',
                 'classification_evidence': ['应力计算表']}
    item = {}
    cs.apply_calculation_sheet(item, candidate, 'Parameter p')
    assert item['table_classification']['evidence_status'] == 'located'
    existing = {'title': 'Different object'}
    cs.apply_calculation_sheet(existing, candidate, 'Parameter p')
    assert existing['table_classification']['reason'] == 'classification_evidence_mismatch'


def test_unclassified_title_does_not_trigger_repair_and_keeps_quality():
    class VLM:
        last_call_info = {}
        def classify_table(self, image, target):
            block = next(b for b in target['evidence_blocks'] if b.get('source_field') == 'title')
            return {'object_ref': target['object_ref'], 'source_sha256': target['source_sha256'],
                    'table_kind': 'calculation_sheet', 'classification_evidence': [
                        {'block_id': block['id'], 'source_sha256': block['source_sha256']}]}
    item = {'title': 'Stress Calculation', 'transcription_quality': {'status': 'incomplete'},
            'table_classification': {'status': 'evidence_unresolved', 'judgment_status': 'model_proposed'}}
    assert cs.repair_table_classification(VLM(), None, item, 'Parameter p', 'table:0', 1) == 0
    assert item['table_classification']['status'] == 'evidence_unresolved'
    assert item['transcription_quality']['status'] == 'incomplete'


def test_single_page_prompt_supplies_independent_title_block():
    prompt = sp._prompt_table_metadata([{'title': '管板计算表', 'markdown': 'Parameter p'}], '')
    assert 'existing_title' in prompt and '管板计算表' in prompt
    assert 'source_content' in prompt and 'Parameter p' in prompt
    assert 'table_kind' not in prompt and 'calculation_sheet' not in prompt




def test_failed_classification_preserves_original_data_table_format():
    item = {'markdown': HTML, 'content_format': 'html', 'columns': ['A'], 'normalized_rows': [['1']]}
    original = copy.deepcopy(item)
    cs.classification_failed(item, 'provider_failed')
    assert item['table_kind'] == 'data_table'
    assert {key: item[key] for key in original} == original
    assert item['table_classification']['reason'] == 'provider_failed'




@pytest.mark.parametrize('outcome', ['data_table', 'uncertain', 'mixed', 'missing', 'invalid', 'failure', 'truncated'])
def test_single_page_fallback_keeps_structure_and_one_semantic_call(outcome):
    from types import SimpleNamespace
    item = {'markdown': HTML, 'columns': ['A'], 'normalized_rows': [['1']],
            'source_cells': [{'row': 0, 'col': 0, 'text': '1'}],
            'contains_images': True, 'image_unresolved': False}
    original = copy.deepcopy(item)
    candidate = {'classification_evidence': ['Inputs'], 'continuation_required': True,
                 'transcription_quality': {'status': 'incomplete', 'evidence': ['missing index']}}
    if outcome != 'missing':
        candidate['table_kind'] = outcome
    class Provider:
        enabled = True
        max_tokens = 4096
        last_call_info = {'finish_reason': 'length' if outcome == 'truncated' else 'stop'}
        calls = 0
        def answer(self):
            self.calls += 1
            if outcome == 'failure':
                raise RuntimeError('stub failure')
            return {'tables': [{'object_ref': 'tables:0', 'index': 0, **candidate}]}
        def extract_region_structured(self, *args, **kwargs):
            return self.answer()
        def _call_image_prompt(self, *args, **kwargs):
            return json.dumps(self.answer())
        def classify_table(self, *args):
            pytest.fail('no extra classification request')
        def transcribe_calculation_blocks(self, *args):
            pytest.fail('no calculation recovery on fallback')
    vlm = Provider()
    calls = {'vlm_ocr': 0}
    sp._enrich_table_metadata_with_vlm(SimpleNamespace(image_path='unused', page_text=''),
        vlm, [item], True, calls, [], 'en')
    assert calls['vlm_ocr'] == 1
    assert vlm.calls == 1
    assert 'table_kind' not in item
    assert {key: item[key] for key in original} == original
    assert 'calculation_source' not in item
    assert 'continuation' not in item
