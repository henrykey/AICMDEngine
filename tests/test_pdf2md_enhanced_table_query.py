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
    req = request(); req['max_model_calls'] = 1; req['query_strategy'] = 'semantic_review'
    p = proposal(req); mutation(p)
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *a: p)
    result = run(req)
    assert result['table'] == req['table']
    out = result['query_enhancement']
    assert out['lookup_sections'] == [] and out['lookup_status'] == 'unavailable'
    assert reason in [i['reason'] for i in out['unresolved']]


def test_truncation_returns_control_and_caller_can_retry(monkeypatch):
    req = request(); req['max_model_calls'] = 1; req['query_strategy'] = 'semantic_review'
    calls = []
    def model(self, payload, language):
        calls.append((deepcopy(payload), language, self.max_retries))
        self.last_call_info = {'truncated': len(calls) == 1}
        return proposal(req)
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', model)
    out = run(req, description_language='zh')['query_enhancement']
    assert out['lookup_status'] == 'unavailable' and out['model_calls'] == 1
    assert len(calls) == 1
    out = run(req, description_language='zh')['query_enhancement']
    assert out['lookup_status'] == 'complete' and out['model_calls'] == 1
    assert all(c[1:] == ('zh', 0) for c in calls)
    assert set(calls[0][0]) == {'binding','source_cells','positions','unresolved'}


def test_provider_failure_safe_and_bounded(monkeypatch):
    req = request(); req['max_model_calls'] = 1; req['query_strategy'] = 'semantic_review'
    def fail(*args):
        raise TimeoutError('SECRET private table response')
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', fail)
    result = run(req)
    assert 'SECRET' not in json.dumps(result)
    assert result['query_enhancement']['model_calls'] == 1
    assert result['query_enhancement']['lookup_sections'] == []


@pytest.mark.parametrize('field,reason', [
    ('content_conflicts', 'content_conflict'),
    ('requires_previous_context', 'missing_previous_context'),
    ('source_assertions', 'content_conflict'),
])
def test_deterministic_blockers_skip_provider(monkeypatch, field, reason):
    req = request(); req['max_model_calls'] = 1
    if field == 'content_conflicts':
        req[field] = [{'reason': 'image disagreement'}]
    elif field == 'requires_previous_context':
        req[field] = True
    else:
        req[field] = [{'source': 'r1c0', 'text': 'WRONG'}]
    calls = []
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *args, **kwargs: calls.append(1))
    out = run(req)['query_enhancement']
    assert out['model_calls'] == 0 and calls == []
    assert out['lookup_sections'] == []
    assert reason in [item['reason'] for item in out['unresolved']]


def test_model_budget_is_cap_and_semantic_review_is_explicit(monkeypatch):
    req = request(); req['max_model_calls'] = 1
    calls = []
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *args, **kwargs: calls.append(1) or proposal(req))
    out = run(req)['query_enhancement']
    assert out['lookup_status'] == 'complete' and out['model_calls'] == 0 and calls == []
    req['query_strategy'] = 'semantic_review'
    out = run(req)['query_enhancement']
    assert out['lookup_status'] == 'complete' and out['model_calls'] == 1 and len(calls) == 1


@pytest.mark.parametrize('strategy,budget,reason', [
    ('model_required', 0, 'invalid_model_budget'),
    ('semantci_review', 1, 'invalid_query_strategy'),
    ('semantic_review', 0, 'invalid_model_budget'),
])
def test_model_strategy_configuration_errors_are_explicit(strategy, budget, reason):
    req = request(); req['query_strategy'] = strategy; req['max_model_calls'] = budget
    out = run(req)['query_enhancement']
    assert out['lookup_status'] == 'unavailable'
    assert out['unresolved'][0]['reason'] == reason


def test_blocker_precheck_has_provider_factory_and_method_zero_calls(monkeypatch):
    req = request(); req['query_strategy'] = 'semantic_review'; req['max_model_calls'] = 1
    req['content_conflicts'] = [{'reason': 'independent image disagrees'}]
    factory_calls = []; method_calls = []
    def factory(config):
        factory_calls.append(config)
        return DynamicVLMClient(config)
    monkeypatch.setattr(single_page_tools, 'DynamicVLMClient', factory)
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *a, **k: method_calls.append(1))
    before = deepcopy(req['table'])
    out = run(req)['query_enhancement']
    assert out['model_calls'] == 0 and factory_calls == [] and method_calls == []
    assert out['unresolved'][0]['reason'] == 'content_conflict'
    assert req['table'] == before


def test_model_required_cannot_be_satisfied_by_deterministic_projection(monkeypatch):
    req = request(); req['query_strategy'] = 'model_required'; req['max_model_calls'] = 1
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    out = run(req)['query_enhancement']
    assert out['model_calls'] == 1
    assert out['lookup_status'] == 'unavailable'
    assert any(item['reason'] == 'model_call_failed' for item in out['unresolved'])


def _real_image_bytes(kind, width=4, height=3):
    import fitz
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    return pix.tobytes(kind)


@pytest.mark.parametrize('kind,mime', [('png', 'image/png'), ('jpeg', 'image/jpeg')])
def test_cross_service_image_requires_real_decodable_payload(monkeypatch, kind, mime):
    req = request(); req['query_strategy'] = 'semantic_review'; req['max_model_calls'] = 1
    import base64
    req['object_image_data'] = 'data:' + mime + ';base64,' + base64.b64encode(_real_image_bytes(kind)).decode()
    seen = []
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda self, payload, language, **kw: seen.append(kw['image_path']) or proposal(req))
    out = run(req)['query_enhancement']
    assert out['model_calls'] == 1 and len(seen) == 1
    assert not __import__('pathlib').Path(seen[0]).exists()


@pytest.mark.parametrize('payload', [
    'data:image/png;base64,' + __import__('base64').b64encode(b'\x89PNG\r\n\x1a\n').decode(),
    'data:image/jpeg;base64,' + __import__('base64').b64encode(b'\xff\xd8\xff').decode(),
    'data:image/png;base64,' + __import__('base64').b64encode(b'\xff\xd8\xff').decode(),
])
def test_invalid_or_mismatched_image_rejected_before_provider(monkeypatch, payload):
    req = request(); req['query_strategy'] = 'semantic_review'; req['max_model_calls'] = 1
    req['object_image_data'] = payload
    calls = []
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *a, **k: calls.append(1))
    out = run(req)['query_enhancement']
    assert out['model_calls'] == 0 and calls == []
    assert out['lookup_status'] == 'unavailable'
    assert out['unresolved'][0]['reason'] == 'invalid_source_reference'


def test_image_transport_uses_real_mime_and_bytes(monkeypatch, tmp_path):
    import base64, json
    image = tmp_path / 'crop.jpg'; image.write_bytes(_real_image_bytes('jpeg'))
    client = DynamicVLMClient({'context_window': 12000})
    client.enabled = True
    client._client = object()
    seen = []
    def wire(**kwargs):
        message = kwargs['messages'][0]['content'][1]['image_url']['url']
        mime, encoded = message.split(';base64,', 1)
        seen.append((mime, base64.b64decode(encoded)))
        return ('{}', 'mock', 'stop')
    monkeypatch.setattr(client, '_chat_completion_with_stream_fallback', wire)
    client._call_image_prompt(str(image), 'input', 128, safe_errors=True)
    assert seen == [('data:image/jpeg', image.read_bytes())]


def test_provider_exception_still_cleans_validated_image(monkeypatch):
    import base64
    req = request(); req['query_strategy'] = 'semantic_review'; req['max_model_calls'] = 1
    req['object_image_data'] = 'data:image/png;base64,' + base64.b64encode(_real_image_bytes('png')).decode()
    paths = []
    def fail(self, payload, language, **kwargs):
        paths.append(kwargs['image_path'])
        raise TimeoutError('provider unavailable')
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', fail)
    out = run(req)['query_enhancement']
    assert out['model_calls'] == 1 and out['lookup_status'] == 'unavailable'
    assert len(paths) == 1 and not __import__('pathlib').Path(paths[0]).exists()


@pytest.mark.parametrize('failure', ['factory', 'client_config'])
@pytest.mark.parametrize('owned', [True, False])
def test_provider_initialization_failure_cleans_only_owned_image(monkeypatch, tmp_path, failure, owned):
    import base64
    original_tempfile = query.tempfile.NamedTemporaryFile
    monkeypatch.setattr(query.tempfile, 'NamedTemporaryFile',
                        lambda **kwargs: original_tempfile(dir=tmp_path, **kwargs))
    req = request(); req.update(query_strategy='semantic_review', max_model_calls=1)
    image_bytes = _real_image_bytes('png')
    caller_image = tmp_path / 'caller.png'
    if owned:
        req['object_image_data'] = base64.b64encode(image_bytes).decode()
    else:
        caller_image.write_bytes(image_bytes)
        req['object_image_path'] = str(caller_image)
    before = deepcopy(req)
    created = []
    methods = []
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *a, **k: methods.append(1))

    def factory(config):
        images = list(tmp_path.glob('pdf2md_table_crop_*'))
        assert len(images) == int(owned)
        created.append(1)
        if failure == 'factory':
            raise RuntimeError('SECRET provider initialization detail')
        return DynamicVLMClient(config)

    result, error = None, None
    try:
        result = query.enhance_table(req, single_page_tools._html_table_to_grid, factory,
                                     {'max_tokens': 'SECRET_invalid'})
    except Exception as exc:
        error = exc
    assert list(tmp_path.glob('pdf2md_table_crop_*')) == []
    if not owned:
        assert caller_image.read_bytes() == image_bytes
    assert error is None
    assert created == [1] and methods == []
    assert req == before and result['table'] == before['table']
    out = result['query_enhancement']
    assert out['model_calls'] == 0 and out['lookup_status'] == 'unavailable'
    assert out['unresolved'] == [{'reason': 'model_initialization_failed', 'sources': []}]
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('outcomes', [('failure', 'success'), ('truncated', 'success'), ('failure', 'failure')])
def test_query_image_cleanup_after_single_attempt(monkeypatch, outcomes):
    import base64
    from pathlib import Path
    req = request(); req.update(query_strategy='semantic_review', max_model_calls=1)
    req['object_image_data'] = base64.b64encode(_real_image_bytes('png')).decode()
    paths = []

    def model(self, payload, language, image_path):
        assert Path(image_path).exists()
        outcome = outcomes[len(paths)]
        paths.append(image_path)
        if outcome == 'failure':
            raise TimeoutError('SECRET provider failure')
        self.last_call_info = {'truncated': outcome == 'truncated'}
        return proposal(req)

    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', model)
    result = run(req)
    assert result['table'] == req['table']
    assert result['query_enhancement']['model_calls'] == 1
    assert result['query_enhancement']['lookup_status'] == 'unavailable'
    assert len(paths) == 1 and all(not Path(path).exists() for path in paths)


def test_cross_service_image_pixel_limit_is_enforced_before_provider(monkeypatch):
    import base64
    req = request(); req['query_strategy'] = 'semantic_review'; req['max_model_calls'] = 1
    req['object_image_data'] = 'data:image/png;base64,' + base64.b64encode(_real_image_bytes('png', 5000, 5000)).decode()
    calls = []
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *a, **k: calls.append(1))
    out = run(req)['query_enhancement']
    assert out['model_calls'] == 0 and calls == []
    assert out['unresolved'][0]['reason'] == 'input_budget_exceeded'


def test_cross_service_object_image_data_is_bounded_and_cleaned(monkeypatch):
    import base64
    req = request(); req['max_model_calls'] = 1; req['query_strategy'] = 'semantic_review'
    req['object_image_data'] = 'data:image/png;base64,' + base64.b64encode(_real_image_bytes('png')).decode()
    paths = []
    def model(self, payload, language, **kwargs):
        paths.append(kwargs.get('image_path'))
        assert kwargs.get('image_path') and __import__('pathlib').Path(kwargs['image_path']).exists()
        return proposal(req)
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', model)
    out = run(req)['query_enhancement']
    assert out['model_calls'] == 1 and len(paths) == 1
    assert not __import__('pathlib').Path(paths[0]).exists()


@pytest.mark.parametrize('expression', ['150~475', '22~33'])
def test_tilde_interval_remains_unresolved_without_boundary_evidence(expression):
    assert query.parse_interval(expression) is None


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
    req = request(markup); req['max_model_calls'] = 1; req['query_strategy'] = 'semantic_review'
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
    req['max_model_calls'] = 1; req['query_strategy'] = 'semantic_review'
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
    req['max_model_calls']=1; req['query_strategy'] = 'semantic_review'
    monkeypatch.setattr(DynamicVLMClient,'explain_table_query',lambda *args:p)
    assert run(req)['query_enhancement']['lookup_status']=='unavailable'


def test_registered_tool_reaches_real_semantic_method_with_wire_stub(monkeypatch):
    req=request(); req['max_model_calls']=1; req['query_strategy'] = 'semantic_review'
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


def test_diagnostics_return_single_failure_without_provider_content(monkeypatch):
    req = request()
    req.update(max_model_calls=1, query_strategy='semantic_review')
    calls = []
    def model(self, payload, language):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError('SECRET provider response')
        self.last_call_info = {}
        return proposal(req)
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', model)
    out = run(req)['query_enhancement']
    assert out['lookup_status'] == 'unavailable'
    assert out['model_calls'] == 1
    assert out['diagnostics'] == [
        {'stage': 'deterministic_projection', 'reasons': []},
        {'stage': 'model_projection', 'attempt': 1, 'reasons': ['model_call_failed']},
        {'stage': 'condition_validation', 'reasons': []},
    ]
    assert 'SECRET' not in json.dumps(out)


def test_query_rejects_multi_attempt_business_budget(monkeypatch):
    req = request(); req.update(max_model_calls=2, query_strategy='semantic_review')
    calls = []
    monkeypatch.setattr(DynamicVLMClient, 'explain_table_query', lambda *a, **kw: calls.append(1))
    out = run(req)['query_enhancement']
    assert calls == []
    assert any(issue['reason'] == 'invalid_model_budget' for issue in out['unresolved'])


@pytest.mark.parametrize("base_url,model,expected", [
    ("https://open.bigmodel.cn/api/paas/v4", "glm-5.3-flash", "high"),
    ("https://open.bigmodel.cn/api/paas/v4", "glm-4.6v-flashx", "default"),
])
def test_query_uses_high_thinking_only_when_supported(base_url, model, expected):
    req = request(); req.update(query_strategy="model_required", max_model_calls=1, thinking_mode="high")
    captured = []
    class Client:
        last_call_info = {}
        physical_requests = 1
        def explain_table_query(self, *args, **kwargs): return {}
    def factory(config):
        captured.append(config)
        return Client()
    result = query.enhance_table(req, single_page_tools._html_table_to_grid, factory,
                                 {"base_url": base_url, "model": model}, "zh")
    assert captured[0]["thinking_mode"] == expected
    assert result["query_enhancement"]["thinking"] == {"requested": "high", "actual": expected}


def test_compact_record_references_are_validated_against_source(monkeypatch):
    req = request(); req.update(query_strategy="semantic_review", max_model_calls=1)
    p = proposal(req)
    for record in p["lookup_sections"][0]["records"]:
        record["values"] = list(record["values"].values())
    monkeypatch.setattr(DynamicVLMClient, "explain_table_query", lambda *args: p)
    out = run(req)["query_enhancement"]
    assert out["lookup_status"] == "complete"
    assert out["lookup_sections"][0]["records"][1]["values"]["c0"]["status"] == "merged_fill"
    p["lookup_sections"][0]["records"][0]["values"].pop()
    out = run(req)["query_enhancement"]
    assert out["lookup_status"] == "unavailable"
    assert "incomplete_record" in [i["reason"] for i in out["unresolved"]]


def test_long_table_compact_records_preserve_all_cells(monkeypatch):
    html = "<table><tr><th>Key</th><th>Value</th></tr>" + "".join(
        f"<tr><td>k{i}</td><td>{i}</td></tr>" for i in range(150)) + "</table>"
    req = request(html); req.update(query_strategy="semantic_review", max_model_calls=1)
    p = proposal(req)
    for record in p["lookup_sections"][0]["records"]:
        record["values"] = list(record["values"].values())
    monkeypatch.setattr(DynamicVLMClient, "explain_table_query", lambda *args: p)
    out = run(req)["query_enhancement"]
    assert out["lookup_status"] == "complete"
    assert len(out["lookup_sections"][0]["records"]) == 150
    assert out["lookup_sections"][0]["records"][-1]["values"]["c1"]["raw_text"] == "149"
    p["lookup_sections"][0]["records"].pop()
    out = run(req)["query_enhancement"]
    assert out["lookup_status"] == "unavailable"
    assert "unmapped_source_cells" in [i["reason"] for i in out["unresolved"]]
