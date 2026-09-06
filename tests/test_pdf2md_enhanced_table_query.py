"""Offline contracts: synthetic sources only, all provider calls stubbed."""
import asyncio
from copy import deepcopy
import hashlib
import importlib
import json

import pytest

from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools, server, DynamicVLMClient

query = importlib.import_module(single_page_tools.__package__ + '.table_query')
HTML = '<table><tr><th rowspan="2">Material</th><th colspan="2">Load</th></tr><tr><th>Low</th><th>High</th></tr><tr><td rowspan="2">0012</td><td>1 1/2</td><td></td></tr><tr><td>8</td><td>8</td></tr></table>'


def request(markup=HTML):
    identity = dict(tenant_id='tenant', doc_id='doc', version=1, table_id='table', table_pk='pk')
    return dict(target=identity, table={**identity, 'render_html': markup, 'markdown': 'unchanged',
                'normalized_rows': [['original']]}, request_id='req',
                source_html_sha256=hashlib.sha256(markup.encode()).hexdigest())


def run(req, **kwargs):
    return json.loads(single_page_tools.extract_page_tables_direct(query_enhancement=req, **kwargs))


def test_multi_header_spans_values_and_immutable_render(monkeypatch):
    monkeypatch.setattr(single_page_tools, '_extract_single_page', lambda **kw: pytest.fail('OCR forbidden'))
    req = request(); before = deepcopy(req)
    result = run(req)
    assert req == before and result['table'] == before['table']
    out = result['query_enhancement']
    assert out['lookup_status'] == 'complete'
    section = out['lookup_sections'][0]
    assert [x['raw_text'] for x in section['fields'][1]['header_path']] == ['Load', 'Low']
    values = section['records'][0]['values']
    assert values['c0']['value'] == '0012' and 'number' not in values['c0']
    assert values['c1']['kind'] == 'fraction'
    assert values['c2']['value'] is None
    assert section['records'][1]['values']['c0']['source'] == 'r2c0'
    assert section['records'][1]['values']['c0']['status'] == 'merged_fill'
    assert section['rows'][1] == ['0012', '8', '8']
    assert out['model_calls'] == 0


@pytest.mark.parametrize('change,reason', [
    (lambda r: r['target'].update(table_id='other'), 'unknown_table_identity'),
    (lambda r: r['target'].pop('table_pk'), 'unknown_table_identity'),
    (lambda r: r.update(source_html_sha256='bad'), 'content_hash_mismatch'),
    (lambda r: r.pop('request_id'), 'request_id_required'),
    (lambda r: r.update(max_model_calls=3), 'invalid_model_budget'),
])
def test_binding_failures(change, reason):
    req = request(); change(req)
    out = run(req)['query_enhancement']
    assert out['lookup_sections'] == []
    assert out['unresolved'][0]['reason'] == reason


@pytest.mark.parametrize('markup', [HTML + HTML, '<table><tr><td>x</td></tr>',
    '<table><tr><th>X</th></tr><tr><td rowspan="5">2</td></tr></table>'])
def test_structural_failures_preserve_table(markup):
    req = request(markup)
    result = run(req)
    assert result['table'] == req['table']
    assert result['query_enhancement']['lookup_status'] == 'unavailable'


def proposal(req):
    binding = {**req['target'], 'request_id': req['request_id'], 'source_html_sha256': req['source_html_sha256']}
    sources, positions, _ = query._sources(req['table']['render_html'], single_page_tools._html_table_to_grid)
    return query._automatic(req['table']['render_html'], sources, positions, binding)


@pytest.mark.parametrize('mutation,reason', [
    (lambda p: p['binding'].update(table_id='other'), 'identity_or_hash_mismatch'),
    (lambda p: p['lookup_sections'][0]['records'][0]['values'].update(c1='r90c5'), 'invalid_source_reference'),
    (lambda p: p['lookup_sections'][0]['records'][0].update(value='999'), 'content_conflict'),
    (lambda p: p['lookup_sections'][0]['records'][0]['values'].update(c1={'value':'999','source':'r2c1'}), 'invalid_source_reference'),
    (lambda p: p['lookup_sections'][0]['records'].pop(), 'unmapped_source_cells'),
    (lambda p: p.update(unresolved=[{'reason':'missing_previous_context','sources':['r2c0']}]), 'missing_previous_context'),
])
def test_model_failures_do_not_publish_or_mutate(monkeypatch, mutation, reason):
    req = request(); req['max_model_calls'] = 1
    p = proposal(req); mutation(p)
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *a: p)
    result = run(req)
    assert result['table'] == req['table']
    out = result['query_enhancement']
    assert out['lookup_sections'] == [] and out['lookup_status'] == 'unavailable'
    assert reason in [i['reason'] for i in out['unresolved']]


def test_bounded_retry_language_and_truncation(monkeypatch):
    req = request(); req['max_model_calls'] = 2
    calls = []
    def model(self, payload, language):
        calls.append((deepcopy(payload), language, self.max_retries))
        self.last_call_info = {'truncated': len(calls) == 1}
        return proposal(req)
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', model)
    out = run(req, description_language='zh')['query_enhancement']
    assert out['lookup_status'] == 'complete' and out['model_calls'] == 2
    assert calls[1][0]['unresolved'][-1]['reason'] == 'model_response_truncated'
    assert all(c[1:] == ('zh', 0) for c in calls)
    assert set(calls[0][0]) == {'binding','source_cells','positions','unresolved'}


def test_provider_failure_safe_and_bounded(monkeypatch):
    req = request(); req['max_model_calls'] = 2
    def fail(*args):
        raise TimeoutError('SECRET private table response')
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', fail)
    result = run(req)
    assert 'SECRET' not in json.dumps(result)
    assert result['query_enhancement']['model_calls'] == 2
    assert result['query_enhancement']['lookup_sections'] == []


def test_annotation_omission_and_content_conflict():
    req = request(); req['annotations'] = [{'kind':'note','text':'Use only after heat treatment'}]
    out = run(req)['query_enhancement']
    assert out['lookup_status'] == 'unavailable'
    assert out['unresolved'][0]['sources'] == ['a0']
    req = request(); req['content_conflicts'] = [{'reason':'independent image disagrees'}]
    out = run(req)['query_enhancement']
    assert out['quality']['content_consistency'] == 'conflict'
    assert out['lookup_sections'] == []


@pytest.mark.parametrize('expression,value,expected', [
    ('84>x≥71', 71, True), ('84>x≥71',84,False), ('x≥71',71,True),
    ('4.9>x≥3.2',3.2,True), ('4.9>x≥3.2',4.9,False), ('-4≤t<7',-4,True),
    ('-4≤t<7',7,False), ('x<=20',20,True),
])
def test_interval_boundaries(expression, value, expected):
    assert query.interval_contains(query.parse_interval(expression),value) is expected


@pytest.mark.parametrize('expression', ['1~5','eval(1)','1<x>5','x+1>3','5<x<1'])
def test_unsupported_interval_is_not_executed(expression):
    assert query.parse_interval(expression) is None


def test_registered_mcp_tool_integration():
    async def invoke():
        tool = await server.mcp.get_tool('extract_page_tables')
        assert 'query_enhancement' in tool.parameters['properties']
        return await tool.run({'query_enhancement': request()})
    result = asyncio.run(invoke())
    parsed = json.loads(result.content[0].text)
    assert parsed["table"] == request()["table"]
    assert parsed["query_enhancement"]["lookup_status"] == "complete"


def test_default_path_has_no_new_arguments(monkeypatch):
    captured = {}
    def extract(**kwargs):
        captured.update(kwargs)
        return {'tables':[{'render_html':'exact'}]}
    monkeypatch.setattr(single_page_tools,'_extract_single_page',extract)
    assert json.loads(single_page_tools.extract_page_tables_direct()) == {'tables':[{'render_html':'exact'}]}
    assert 'query_enhancement' not in captured


def test_text_span_conditions_are_required_and_source_bound(monkeypatch):
    markup = '<table><tr><th>Material</th><th>Curve</th></tr><tr><td>Alloy Z if annealed</td><td>Q</td></tr></table>'
    req = request(markup); req['max_model_calls'] = 1
    p = {'binding': {**req['target'], 'request_id':'req','source_html_sha256':req['source_html_sha256']},
         'lookup_sections':[{'key':'section_1','fields':[{'key':'c0','header_path':['r0c0']},{'key':'c1','header_path':['r0c1']}],
         'records':[{'values':{'c0':'r1c0','c1':'r1c1'}}]}], 'unresolved':[]}
    record = p['lookup_sections'][0]['records'][0]
    record['values']['c0'] = {'source':'r1c0','start':0,'end':7}
    record['conditions'] = [{'source':'r1c0','start':8,'end':19}]
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *args:p)
    out = run(req)['query_enhancement']
    assert query.select_records(out,'section_1',{'c0':'Alloy Z'}) == []
    found = query.select_records(out,'section_1',{'c0':'Alloy Z'},['r1c0:8:19'])
    assert found[0]['values']['c1']['value'] == 'Q'
    assert found[0]['conditions'][0]['raw_text'] == 'if annealed'
    record.pop('conditions')
    out = run(req)['query_enhancement']
    assert out['lookup_status'] == 'unavailable'
    assert out['unresolved'][-1]['reason'] == 'unmapped_source_cells'


def test_source_assertion_and_revision():
    req = request(); req['table']['override_revision'] = 7
    assert run(req)['query_enhancement']['unresolved'][0]['reason'] == 'revision_or_page_mismatch'
    req['target']['override_revision'] = 7
    req['source_assertions'] = [{'source':'r3c1','text':'9'}]
    out = run(req)['query_enhancement']
    assert out['quality']['content_consistency'] == 'conflict'
    assert out['unresolved'][0] == {'reason':'content_conflict','sources':['r3c1']}


def test_bbox_preserved_only_for_matching_source():
    req = request(); req['table']['source_cells'] = [{'row':2,'col':0,'text':'0012','bbox':[1,2,3,4]}]
    out = run(req)['query_enhancement']
    assert out['lookup_sections'][0]['records'][0]['values']['c0']['bbox'] == [1,2,3,4]


def test_real_client_prompt_and_budget_are_stubbed(monkeypatch):
    client = DynamicVLMClient({'context_window':10000})
    captured = {}
    def wire(prompt, max_tokens, safe_errors=False):
        assert safe_errors
        captured.update(prompt=prompt, max_tokens=max_tokens)
        return '{"binding":{},"lookup_sections":[],"unresolved":[]}'
    monkeypatch.setattr(client,'_call_text_prompt',wire)
    client.explain_table_query({'binding':{}},'zh')
    assert 'Chinese' in captured['prompt'] and 'untrusted' in captured['prompt']
    assert 0 < captured['max_tokens'] <= client.max_tokens
    with pytest.raises(ValueError, match='input_budget_exceeded'):
        client.explain_table_query({'source_cells':'x' * 20000},'en')


def test_reversed_and_latex_intervals():
    assert query.interval_contains(query.parse_interval('9>x'),8)
    assert query.interval_contains(query.parse_interval(r'$20>\\mathrm{EEI}\\geq 10$'.replace('\\\\','\\')),10)


def test_same_material_different_conditions_and_units(monkeypatch):
    req = request('<table><tr><th>Material</th><th>Limit</th></tr><tr><td>Z</td><td>9</td></tr><tr><td>Z</td><td>9</td></tr></table>')
    p = proposal(req)
    req['annotations'] = [{'text':'annealed'},{'text':'quenched'},{'text':'MPa'}]
    p['lookup_sections'][0]['fields'][1]['unit_sources'] = ['a2']
    p['lookup_sections'][0]['records'][0]['conditions'] = ['a0']
    p['lookup_sections'][0]['records'][1]['conditions'] = ['a1']
    req['max_model_calls'] = 1
    monkeypatch.setattr(DynamicVLMClient,'explain_table_query',lambda *args:p)
    out = run(req)['query_enhancement']
    assert len(out['lookup_sections'][0]['records']) == 2
    assert out['lookup_sections'][0]['fields'][1]['units'][0]['raw_text'] == 'MPa'
    assert len(query.select_records(out,'section_1',{'c0':'Z'},['a0:0:8'])) == 1


def test_blank_row_keeps_original_source_coordinates():
    req=request('<table><tr><th>X</th></tr><tr><td></td></tr><tr><td>4</td></tr></table>')
    rows=run(req)['query_enhancement']['lookup_sections'][0]['records']
    assert rows[0]['values']['c0']['value'] is None
    assert rows[1]['values']['c0']['source']=='r2c0'


def test_conditional_text_requires_semantic_interpretation():
    req=request('<table><tr><th>Material</th></tr><tr><td>Z if annealed</td></tr></table>')
    assert run(req)['query_enhancement']['lookup_status']=='unavailable'


def test_fullwidth_comparisons():
    assert query.interval_contains(query.parse_interval('33＞T≥22'),22)
    assert not query.interval_contains(query.parse_interval('33＞T≥22'),33)


def test_invalid_config_does_not_leak_value():
    req=request(); req['max_model_calls']=1
    assert 'SECRET' not in json.dumps(run(req,vlm_config={'timeout_sec':'SECRET'}))


def test_optional_crop_uses_existing_image_client(monkeypatch):
    client=DynamicVLMClient({'context_window':12000})
    seen=[]
    def wire(path,prompt,max_tokens,safe_errors=False):
        seen.append(path)
        assert safe_errors and 'content_conflict' in prompt
        return '{}'
    monkeypatch.setattr(client,'_call_image_prompt',wire)
    client.explain_table_query({'binding':{}},'en',image_path='/explicit/object.png')
    assert seen==['/explicit/object.png']


def test_numeric_token_cannot_be_sliced_to_a_different_number(monkeypatch):
    req=request('<table><tr><th>X</th></tr><tr><td>-123</td></tr></table>')
    p=proposal(req); p['lookup_sections'][0]['records'][0]['values']['c0']={'source':'r1c0','start':1,'end':4}
    p['lookup_sections'][0]['records'][0]['groups']=[{'source':'r1c0','start':0,'end':1}]
    req['max_model_calls']=1
    monkeypatch.setattr(DynamicVLMClient,'explain_table_query',lambda *args:p)
    assert run(req)['query_enhancement']['lookup_status']=='unavailable'


def test_registered_tool_reaches_real_semantic_method_with_wire_stub(monkeypatch):
    req=request(); req['max_model_calls']=1
    seen=[]
    def wire(self,prompt,max_tokens,safe_errors=False):
        payload=json.loads(prompt.split('\nInput: ',1)[1])
        seen.append(payload['binding'])
        assert safe_errors
        return json.dumps(proposal(req))
    monkeypatch.setattr(DynamicVLMClient,'_call_text_prompt',wire)
    async def invoke():
        tool=await server.mcp.get_tool('extract_page_tables')
        return await tool.run({'query_enhancement':req,'vlm_config':{'context_window':16000}})
    result=json.loads(asyncio.run(invoke()).content[0].text)
    assert result['query_enhancement']['model_calls']==1
    assert result['query_enhancement']['lookup_status']=='complete'
    assert result['table']==req['table'] and len(seen)==1


def test_query_transport_diagnostics_do_not_log_provider_text(caplog):
    import types
    client=DynamicVLMClient({'max_retries':0})
    def fail(**kwargs):
        raise RuntimeError('SECRET table content')
    client.enabled=True
    client._client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=fail)))
    with pytest.raises(RuntimeError,match='model_call_failed'):
        client._call_text_prompt('private prompt',256,safe_errors=True)
    assert 'SECRET' not in caplog.text


def test_both_runtime_manifests_include_query_module():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'mcp/servers/PDF2MDEnhanced'
    for name in ('Dockerfile','Dockerfile.cn'):
        assert 'table_query.py' in next(line for line in (root/name).read_text().splitlines() if line.startswith('COPY __init__.py'))
