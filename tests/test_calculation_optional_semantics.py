import asyncio
import copy
import importlib
import pytest
from tests.test_pdf2md_calculation_processing import cp, DynamicVLMClient


def sheet():
    return {'semantic_desc': 'Sheet purpose', 'sections': [{'title': 'Limits', 'items': [
        {'id': 'a', 'kind': 'formula', 'latex': 'a=b', 'sources': ['a=b'], 'semantic_desc': ''},
        {'id': 'b', 'kind': 'formula', 'latex': 'c=d', 'sources': ['c=d'], 'semantic_desc': ''}]}]}


def test_optional_timeout_keeps_structure_and_continues():
    value = sheet(); before = copy.deepcopy(value); seen = []
    class Provider:
        def describe_calculation_formula(self, item, context):
            seen.append(item['id'])
            if item['id'] == 'a': raise TimeoutError()
            return 'The source expresses the relation between c and d.'
    cp.complete_optional_formula_semantics(Provider(), value)
    assert seen == ['a', 'b']
    assert value['sections'][0]['items'][0]['semantic_status'] == 'optional_timeout'
    assert value['sections'][0]['items'][1]['semantic_desc']
    assert value['semantic_desc'] == before['semantic_desc']
    for actual, original in zip(value['sections'][0]['items'], before['sections'][0]['items']):
        assert actual['latex'] == original['latex'] and actual['sources'] == original['sources']


def test_existing_description_is_not_overwritten():
    value = sheet(); value['sections'][0]['items'] = [dict(value['sections'][0]['items'][0], semantic_desc='Human text')]
    class Provider:
        def describe_calculation_formula(self, *args): raise AssertionError('must not call')
    cp.complete_optional_formula_semantics(Provider(), value)
    assert value['sections'][0]['items'][0]['semantic_desc'] == 'Human text'


def test_deadline_cancels_slow_formula():
    client = DynamicVLMClient({})
    cancelled = []
    async def slow(*args):
        try: await asyncio.sleep(2)
        finally: cancelled.append(True)
    client._request_formula_description = slow
    client.formula_semantic_timeout_sec = .01
    with pytest.raises(TimeoutError):
        client.describe_calculation_formula({'latex': 'a=b'}, {'title': 'test'})
    assert cancelled == [True]


def test_optional_request_uses_one_send_and_no_sdk_retry(monkeypatch):
    import openai
    from types import SimpleNamespace
    captured=[]
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs['max_retries']==0
            self.http=kwargs['http_client'];self.chat=SimpleNamespace(completions=self)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): await self.http.aclose()
        async def create(self,**kwargs):
            captured.append(kwargs)
            for hook in self.http.event_hooks['request']: await hook(None)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
                message=SimpleNamespace(content='The expression relates a to b.'))])
    monkeypatch.setattr(openai,'AsyncOpenAI',FakeClient)
    client=DynamicVLMClient({'model':'fixture','api_key':'fixture','base_url':'http://invalid.local/v1',
                             'table_analysis_max_physical_requests':1})
    try:
        text=client.describe_calculation_formula({'latex':'a=b','sources':['a=b']},{'section_title':'Relation'})
        assert text and len(captured)==1 and client.physical_requests==1
        assert captured[0]['stream'] is False and captured[0]['timeout']==15
        with pytest.raises(Exception):
            client.describe_calculation_formula({'latex':'a=b'}, {})
        assert client.physical_requests==1
    finally: client._client.close()


@pytest.mark.parametrize('timeout', [False, True])
def test_explicit_optional_rpc_describes_only_one_formula_and_never_restructures(timeout):
    from tests.test_pdf2md_calculation_processing import request
    req = request(); req.update(stage='formula_description', existing_content='$a=b$\n$c=d$',
                                formula={'id': 'a', 'kind': 'formula', 'latex': 'a=b', 'sources': ['a=b']})
    seen = []
    class Provider:
        table_analysis_max_model_calls = 8
        def extract_calculation_sheet(self, *args): raise AssertionError('must not restructure')
        def describe_calculation_formula(self, item, context):
            seen.append(item['id'])
            if timeout: raise TimeoutError()
            return 'The relation defines a in terms of b.'
    out = cp.process_request(req, 'calculation_sheet', 'organize_existing', Provider())
    assert seen == ['a']
    assert out['formula_description']['id'] == 'a'
    assert out['formula_description']['semantic_status'] == ('optional_timeout' if timeout else 'model_proposed')
    assert 'calculation_sheet' not in out


def test_single_formula_stage_through_public_table_tool(monkeypatch):
    import json
    from tests.test_pdf2md_calculation_processing import request, sp
    req = request()
    req.update(stage='formula_description', existing_content='$a=b$',
               formula={'id': 'a', 'kind': 'formula', 'latex': 'a=b', 'sources': ['a=b']})
    seen = []
    class Provider:
        table_analysis_max_model_calls = 8
        def extract_calculation_sheet(self, *args):
            raise AssertionError('optional operation must not restructure')
        def describe_calculation_formula(self, item, context):
            seen.append(item['id'])
            return 'Defines a in terms of b.'
    monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: Provider())
    out = json.loads(sp.extract_page_tables_direct(processing_mode='organize_existing',
                    table_kind_hint='calculation_sheet', context={'calculation_request': req}))
    assert seen == ['a']
    assert out['formula_description']['semantic_desc'] == 'Defines a in terms of b.'
    assert out['calculation_identity'] == req['identity']
    assert 'calculation_sheet' not in out
