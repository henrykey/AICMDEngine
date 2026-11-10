import asyncio
import base64
import json

from PIL import Image

from tests.test_pdf2md_enhanced_single_page_tools import server
from tests.test_pdf2md_enhanced_task_manager import TaskManager


def test_page_rate_limit_is_identified_and_same_page_can_retry(tmp_path, monkeypatch):
    image = tmp_path / 'page.png'
    Image.new('RGB', (20, 20), 'white').save(image)
    manager = TaskManager(str(tmp_path / 'output'))
    task = manager.start_task('rate-limit', file_data=base64.b64encode(image.read_bytes()).decode(), pages=[1])
    monkeypatch.setattr(server, 'manager', manager)
    calls = []

    class RateLimited(Exception):
        status_code = 429

    def process(*args):
        calls.append(args[1])
        if len(calls) == 1:
            try:
                raise RateLimited('synthetic limit')
            except RateLimited as error:
                raise ValueError('layout failed') from error
        return {'render': {'markdown': 'done'}}

    monkeypatch.setattr(server, 'process_page', process)
    fn = getattr(server.process_task_page, 'fn', server.process_task_page)

    async def run():
        first = json.loads(await fn(task_id=task.task_id, page_no=1))
        assert first.get('error_code') == 'MODEL_RATE_LIMITED'
        second = json.loads(await fn(task_id=task.task_id, page_no=1))
        assert second['page_result']['render']['markdown'] == 'done'

    asyncio.run(run())
    assert calls == [1, 1]


def test_quota_exhaustion_is_not_treated_as_temporary_limit():
    class QuotaError(Exception):
        status_code = 429
        body = {'error': {'code': 'insufficient_quota'}}

    assert not server._model_rate_limited(QuotaError())


def test_provider_wrappers_preserve_safe_rate_limit(tmp_path, monkeypatch, caplog):
    from tests.test_pdf2md_enhanced_single_page_tools import OpenAICompatibleOcrClient, page_processor
    DynamicVLMClient = page_processor.DynamicVLMClient
    image = tmp_path / 'page.png'
    Image.new('RGB', (10, 10)).save(image)

    class RateLimited(Exception):
        status_code = 429

    def fail(*args, **kwargs):
        raise RateLimited('secret prompt and provider response')

    ocr = OpenAICompatibleOcrClient({}, source='fixture')
    ocr.max_retries = 0
    ocr._client = type('Client', (), {'chat': type('Chat', (), {'completions': type('Completions', (), {'create': fail})()})()})()
    vlm = DynamicVLMClient({})
    vlm.ensure_enabled = lambda: None
    vlm.max_retries = 0
    vlm._chat_completion_with_stream_fallback = fail
    for call in (lambda: ocr._call_image_prompt(str(image), 'prompt'),
                 lambda: vlm._call_image_prompt(str(image), 'prompt', 100)):
        try:
            call()
            assert False
        except RuntimeError as exc:
            assert server._model_rate_limited(exc)
            assert 'secret' not in str(exc)
    assert 'secret' not in caplog.text


def test_async_failed_operation_can_be_polled_then_retried(monkeypatch):
    fn = getattr(server.process_task_page, 'fn', server.process_task_page)
    monkeypatch.setattr(server.manager, 'validate_source_identity', lambda *args: None)
    calls = []

    async def work(task_id, page_no, *args):
        calls.append(page_no)
        args[-1].set()
        if len(calls) == 1:
            return json.dumps({'task_id': task_id, 'page_no': page_no, 'error': 'limited', 'error_code': 'MODEL_RATE_LIMITED'})
        return json.dumps({'task_id': task_id, 'page_no': page_no, 'page_result': {}})

    monkeypatch.setattr(server, '_process_task_page', work)
    async def run():
        config = {'calculation_async': True}
        first = json.loads(await fn('async-test', 1, routing_config=config))
        assert first['error_code'] == 'MODEL_RATE_LIMITED'
        poll = json.loads(await fn('async-test', 1, routing_config={**config, 'calculation_poll': True}))
        assert poll['error_code'] == 'MODEL_RATE_LIMITED'
        retry = json.loads(await fn('async-test', 1, routing_config=config))
        assert 'page_result' in retry
    try:
        asyncio.run(run())
        assert calls == [1, 1]
    finally:
        server._calculation_page_operations.pop(('async-test', 1), None)


def test_layout_provider_error_reaches_page_tool_safely(tmp_path, monkeypatch, caplog):
    import io
    import urllib.error
    import time
    from tests.test_pdf2md_enhanced_single_page_tools import OpenAICompatibleOcrClient
    image = tmp_path / 'page.png'
    Image.new('RGB', (20, 20), 'white').save(image)
    manager = TaskManager(str(tmp_path / 'output'))
    task = manager.start_task('provider', file_data=base64.b64encode(image.read_bytes()).decode(), pages=[1])
    monkeypatch.setattr(server, 'manager', manager)
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    fn = getattr(server.process_task_page, 'fn', server.process_task_page)
    config = {'glm_ocr': {'enabled': True, 'model': 'test', 'base_url': 'https://example.invalid', 'mode': 'layout_parsing'}}
    for status, code, expected in [(429, 'rate_limit', 'MODEL_RATE_LIMITED'),
                                    (429, 'insufficient_quota', 'MODEL_QUOTA_EXHAUSTED'),
                                    (401, 'invalid_api_key', 'MODEL_AUTH_FAILED'),
                                    (500, 'other', None)]:
        def fail(self, request):
            body = json.dumps({'error': {'code': code, 'message': 'secret document prompt'}}).encode()
            raise urllib.error.HTTPError(request.full_url, status, 'secret', {}, io.BytesIO(body))
        monkeypatch.setattr(OpenAICompatibleOcrClient, '_open_request', fail)
        result = json.loads(asyncio.run(fn(task.task_id, 1, ocr_config=config)))
        assert result.get('error_code') == expected
        assert result['task_id'] == task.task_id and result['page_no'] == 1
        assert 'page_result' not in result
        assert 'secret' not in json.dumps(result)
    assert 'secret' not in caplog.text


def test_other_tools_report_provider_errors_and_identity(tmp_path, monkeypatch):
    import importlib
    import pytest
    from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools
    from tests.test_pdf2md_object_semantics import request
    obj = importlib.import_module(single_page_tools.__package__ + '.object_semantics')
    image = tmp_path / 'page.png'
    Image.new('RGB', (20, 20), 'white').save(image)
    data = base64.b64encode(image.read_bytes()).decode()
    class ProviderError(Exception):
        pass
    class Vlm:
        enabled = True
        max_tokens = 100
        physical_requests = 1
        def __init__(self, *args, **kwargs): pass
        def _call_image_prompt(self, *args, **kwargs): raise error
        def _call_text_prompt(self, *args, **kwargs): raise error
    monkeypatch.setattr(single_page_tools, 'DynamicVLMClient', Vlm)
    monkeypatch.setattr(obj, 'DynamicVLMClient', Vlm)
    for status, body, expected in [(429, {}, 'MODEL_RATE_LIMITED'),
                                    (429, {'error': {'code': 'insufficient_quota'}}, 'MODEL_QUOTA_EXHAUSTED'),
                                    (401, {}, 'MODEL_AUTH_FAILED')]:
        error = ProviderError('secret payload')
        error.status_code = status
        error.body = body
        revise = getattr(server.revise_page_markdown, 'fn', server.revise_page_markdown)
        result = json.loads(asyncio.run(revise(file_data=data, page_no=1)))
        assert result == {'error': expected.lower(), 'error_code': expected, 'page_no': 1}
        semantic = getattr(server.enhance_object_semantics, 'fn', server.enhance_object_semantics)
        result = json.loads(asyncio.run(semantic({**request(), 'request_id': 'req-1'})))
        assert result['error_code'] == expected and result['request_id'] == 'req-1'
        assert (result['element_type'], result['element_id']) == ('formula', 'o1')
        assert 'secret' not in json.dumps(result)


def test_page_semantics_and_direct_tools_preserve_ids(monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools
    class RateLimited(Exception):
        status_code = 429
    def fail(*args, **kwargs): raise RateLimited('secret')
    monkeypatch.setattr(single_page_tools, 'enhance_saved_page_table_semantics', fail)
    fn = getattr(server.enhance_page_object_semantics, 'fn', server.enhance_page_object_semantics)
    result = json.loads(asyncio.run(fn('table', [{'table_id': 't1', 'layout_id': 'l1'}],
        source_identity={'doc_id': 'd1', 'source_page_no': 3})))
    assert result == {'error': 'model_rate_limited', 'error_code': 'MODEL_RATE_LIMITED',
        'object_type': 'table', 'source_identity': {'doc_id': 'd1', 'source_page_no': 3},
        'targets': [{'table_id': 't1', 'layout_id': 'l1'}]}
    for name, direct in [('extract_page_tables', 'extract_page_tables_direct'),
                         ('extract_page_formulas', 'extract_page_formulas_direct'),
                         ('extract_page_figures', 'extract_page_figures_direct'),
                         ('extract_page_structured', 'extract_page_structured_direct'),
                         ('extract_page_layout_enhanced', 'extract_page_layout_enhanced_direct'),
                         ('analyze_page_layout', 'analyze_page_layout_direct')]:
        monkeypatch.setattr(server, direct, fail)
        fn = getattr(getattr(server, name), 'fn', getattr(server, name))
        result = json.loads(asyncio.run(fn(page_no=4)))
        assert result == {'error': 'model_rate_limited', 'error_code': 'MODEL_RATE_LIMITED', 'page_no': 4}


def test_page_semantics_provider_chain_for_table_and_formula(monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools
    class RateLimited(Exception):
        status_code = 429
    class Vlm:
        enabled = True
        max_tokens = 4096
        def __init__(self, config): pass
        def _call_text_prompt(self, *args, **kwargs): raise RateLimited('private')
    monkeypatch.setattr(single_page_tools, 'DynamicVLMClient', Vlm)
    fn = getattr(server.enhance_page_object_semantics, 'fn', server.enhance_page_object_semantics)
    for kind, target, fallback in [
        ('table', {'table_id': 't', 'layout_id': 'l'}, {'page_no': 3, 'page_text': 'context', 'tables': [{'layout_id': 'l', 'markdown': 'table'}]}),
        ('formula', {'formula_id': 'f', 'layout_id': 'l'}, {'page_no': 3, 'page_text': 'context', 'formulas': [{'layout_id': 'l', 'latex': 'x=y'}]})]:
        result = json.loads(asyncio.run(fn(kind, [target], fallback_page=fallback)))
        assert result == {'error': 'model_rate_limited', 'error_code': 'MODEL_RATE_LIMITED',
                          'object_type': kind, 'page_no': 3, 'targets': [target]}
