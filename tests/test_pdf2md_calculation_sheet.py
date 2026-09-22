"""Calculation sheets: source-bound offline contracts, no providers."""
import copy
import importlib
import json

import pytest
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools as sp
from tests.test_pdf2md_enhanced_upload_semantics import pp

cs = importlib.import_module(sp.__package__ + '.calculation_sheet')
HTML = '<table><tr><td rowspan="14">Inputs</td><td>Pressure p MPa</td></tr><tr><td>Calculation</td><td>Force $F=pA$ N</td></tr><tr><td>Check</td><td>When p&gt;0, F&lt;10</td></tr></table>'


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
    assert 'table_kind' not in item
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
    assert result == fixture['mcp_response']


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
def test_unsupported_type_is_review_only(kind):
    item = {'markdown': HTML}; p = proposal(); p['table_kind'] = kind
    cs.apply_calculation_sheet(item, p, HTML)
    assert item['manualReviewRequired'] is True
    assert not item.get('calculation_sheet', {}).get('sections')


def test_data_table_unchanged():
    item = {'markdown': HTML}; cs.apply_calculation_sheet(item, {'table_kind':'data_table','classification_evidence':['Inputs']}, HTML)
    assert item['markdown'] == HTML
    assert 'calculation_sheet' not in item
    assert 'lookup_status' not in item


def test_upload_reuses_one_semantic_call_and_survives_normalization():
    calls = []
    class VLM:
        def extract_region_structured(self, image_path, semantic_objects):
            calls.append(semantic_objects)
            assert 'calculation_source' in semantic_objects[0]
            return {'tables': [{'object_ref': 'tables:0', **proposal()}]}
    item = {'markdown': HTML, 'layout_id':'p1-t1'}
    payloads = {'tables': [item]}
    assert pp._enrich_upload_semantics(VLM(), 'unused.png', {}, payloads, True) == 1
    assert len(calls) == 1
    assert item['table_kind'] == 'calculation_sheet'
    normalized = pp._normalize_structured(payloads)
    out = pp._build_output_elements('', normalized, 'full_glm_ocr')['tables'][0]
    assert out['calculation_sheet']['validation_status'] == 'source_validated'


def test_metadata_merge_single_page_and_query_guard():
    item = {'markdown': HTML, 'raw_html': HTML}
    sp._merge_table_metadata([item], [{'index':0, **proposal()}])
    assert item['table_kind'] == 'calculation_sheet'
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


def test_single_page_glm_classifies_before_any_grid_call(monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import (
        _patch_clients, FakeGLMOcrClient, FakeVLMClient, OcrResult, OcrElement, PNG_DATA)
    _patch_clients(monkeypatch)
    FakeGLMOcrClient.result = OcrResult(tables=[OcrElement(kind='table', source='glm_ocr', markdown=HTML)])
    monkeypatch.setattr(FakeVLMClient, 'result_text', json.dumps({'tables':[{'index':0, **proposal()}]}))
    monkeypatch.setattr(sp, '_html_table_to_grid', lambda *_: pytest.fail('classification must precede grid'))
    out = json.loads(sp.extract_page_tables_direct(file_data=PNG_DATA, input_type='image',
        ocr_config={'glm_ocr': {'enabled':True, 'model':'stub', 'api_key':'stub', 'base_url':'http://stub'}},
        vlm_config={'model':'stub', 'api_key':'stub', 'base_url':'http://stub'}))
    assert out['model_calls'] == {'glm_ocr':1, 'vlm_ocr':1}
    assert out['table_kind'] == 'calculation_sheet'
    assert out['columns'] == [] and out['normalized_rows'] == []
    assert out['tableRowsContent'] == ''
    assert '_pending_grid' not in out['tables'][0]
    assert out['calculation_sheet']['validation_status'] == 'source_validated'


def test_single_page_vlm_calculation_response_bypasses_grid(monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import OcrElement
    monkeypatch.setattr(sp, '_html_table_to_grid', lambda *_: pytest.fail('not a grid'))
    raw = {'markdown':HTML, **proposal(), 'bbox':[.1,.1,.8,.8], 'bbox_space':'normalized_page'}
    item = sp._table_item('vlm_ocr', HTML, '', True, OcrElement(kind='table', source='vlm_ocr', markdown=HTML, raw=raw))
    assert item['calculation_sheet']['sections'][0]['items'][0]['source']['bbox'] == raw['bbox']
    assert item['markdown'] == HTML


def test_disabled_semantics_makes_zero_calls():
    class Forbidden:
        def extract_region_structured(self, *args, **kwargs):
            pytest.fail('disabled means no model')
    payload = {'tables':[{'markdown':HTML}]}
    assert pp._enrich_upload_semantics(Forbidden(), 'unused', {}, payload, False) == 0


def test_foreign_or_duplicate_upload_reference_not_applied():
    class VLM:
        def extract_region_structured(self, *args, **kwargs):
            return {'tables':[{'object_ref':'tables:0', **proposal()}]*2 + [{'object_ref':'tables:1', **proposal()}]}
    payload = {'tables':[{'markdown':HTML}]}
    assert pp._enrich_upload_semantics(VLM(), 'unused', {}, payload, True) == 1
    assert 'calculation_sheet' not in payload['tables'][0]


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
    assert item['table_kind'] == 'uncertain'


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
    assert item['table_kind'] == 'uncertain'


def test_upload_truncated_response_not_accepted():
    class VLM:
        last_call_info = {'finish_reason':'length'}
        def extract_region_structured(self, *args, **kwargs):
            return {'tables':[{'object_ref':'tables:0', **proposal()}]}
    payload={'tables':[{'markdown':HTML}]}
    assert pp._enrich_upload_semantics(VLM(), 'unused', {}, payload, True) == 1
    assert 'calculation_sheet' not in payload['tables'][0]


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


@pytest.mark.parametrize('budget,expected_calls', [(0,0),(1,1),(2,2)])
def test_two_stage_upload_has_shared_budget(budget, expected_calls):
    events=[]
    class VLM:
        table_analysis_max_model_calls=budget
        def extract_region_structured(self, path, semantic_objects):
            events.append('classify')
            p=proposal();p.pop('calculation_sheet')
            return {'tables':[{'object_ref':'tables:0',**p}]}
        def extract_calculation_sheet(self,path,target):
            events.append('extract')
            assert target['source_sections']
            return {'object_ref':target['object_ref'], 'source_sha256':target['source_sha256'],
                    'sections': [{'title':g['title'], 'items':[{'source_item_id':u['id'], 'kind':'note'} for u in g['items']]}
                                 for g in target['source_sections']], 'unresolved':[], 'image_discrepancies':[]}
    payload={'tables':[{'markdown':HTML}]}
    assert pp._enrich_upload_semantics(VLM(),'unused',{},payload,True)==expected_calls
    assert len(events)==expected_calls
    if budget==2:
        assert events==['classify','extract']
        assert payload['tables'][0]['calculation_sheet']['validation_status']=='source_validated'
    elif budget==1:
        assert payload['tables'][0]['calculation_sheet']['unresolved']==[{'reason':'table_analysis_budget_exhausted'}]


def test_two_tables_do_not_each_receive_a_fresh_budget():
    events=[]
    class VLM:
        table_analysis_max_model_calls=2
        def extract_region_structured(self,path,semantic_objects):
            p=proposal();p.pop('calculation_sheet')
            return {'tables':[{'object_ref':t['object_ref'],**p} for t in semantic_objects]}
        def extract_calculation_sheet(self,path,target):
            events.append(target['object_ref'])
            return {**target, **proposal()['calculation_sheet']}
    payload={'tables':[{'markdown':HTML},{'markdown':HTML}]}
    assert pp._enrich_upload_semantics(VLM(),'unused',{},payload,True)==2
    assert events==['tables:0']
    assert payload['tables'][1]['calculation_sheet']['unresolved']==[{'reason':'table_analysis_budget_exhausted'}]


@pytest.mark.parametrize('mode,reason', [('wrong_id','calculation_identity_mismatch'),('truncated','calculation_response_incomplete'),('failure','calculation_provider_failed')])
def test_dedicated_parser_checks_identity_and_provider_failure(mode,reason):
    class VLM:
        last_call_info={'finish_reason':'length' if mode=='truncated' else 'stop'}
        def extract_calculation_sheet(self,path,target):
            if mode=='failure':raise RuntimeError('private provider details')
            return {'object_ref':'wrong' if mode=='wrong_id' else target['object_ref'],
                    'source_sha256':target['source_sha256'],**proposal()['calculation_sheet']}
    item={};cs.extract_calculation_items(VLM(),'unused',item,HTML,'tables:0')
    assert item['calculation_sheet']['unresolved']==[{'reason':reason}]
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
