"""Identity and bounded cross-page processing; all model responses are synthetic."""
import asyncio
import base64
import copy
import importlib
import json
from pathlib import Path

import fitz
import pytest

from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools as sp, server, DynamicVLMClient

cp = importlib.import_module(sp.__package__ + '.calculation_processing')


def fixture():
    return json.loads((Path(__file__).parent / 'fixtures/calculation_processing_contract.json').read_text())


def request():
    return copy.deepcopy(fixture()['request']['context']['calculation_request'])


def response(identity, text='Table 1.2\nPressure p = MPa', kind='calculation_sheet'):
    return {'object_ref': identity['layout_id'], 'source_sha256': identity['source_sha256'],
            'table_kind': kind, 'source_text': text, 'classification_evidence': [text],
            'sections': [{'title': 'Pressure', 'items': [{'kind': 'note', 'name': 'Pressure', 'sources': [text]}]}],
            'unresolved': [], 'image_discrepancies': [], 'continuation': {'status': 'none'}}


class Provider:
    enabled = True
    table_analysis_max_model_calls = 2
    last_call_info = {}
    description_language = 'en'

    def __init__(self, *responses):
        self.responses = list(responses); self.calls = []

    def extract_calculation_sheet(self, images, target):
        self.calls.append((images, target))
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return copy.deepcopy(value)


def adjacent(req, offset=-1):
    identity = {**req['identity'], 'page_no': req['identity']['page_no'] + offset,
                'layout_id': f'adjacent-{offset}', 'table_pk': f'adjacent-pk-{offset}'}
    obj = {'identity': identity, 'source_text': 'Table 1.2\nPressure on previous page'}
    req['adjacent_objects'] = [obj]
    return obj


@pytest.mark.parametrize('key,value', [('tenant_id', 'foreign'), ('doc_id', 'foreign'),
    ('version', 2), ('source_sha256', 'b'*64), ('page_no', 8), ('layout_id', 'p2-o001-table')])
def test_wrong_adjacent_scope_never_calls_model(key, value):
    req = request(); obj = adjacent(req); obj['identity'][key] = value; vlm = Provider()
    out = cp.process_request(req, 'auto', 'auto', vlm, 'current.png', ['previous.png'])
    assert out['reason'] == 'adjacent_context_invalid'
    assert not vlm.calls


@pytest.mark.parametrize('budget', [0, True, -1, 9, '2'])
def test_invalid_or_exhausted_budget_is_explicit(budget):
    vlm = Provider(); vlm.table_analysis_max_model_calls = budget
    out = cp.process_request(request(), 'calculation_sheet', 'reextract', vlm, 'image')
    assert out['reason'] == 'table_analysis_budget_exhausted'
    assert out['table_kind_source'] == 'manual'
    assert not vlm.calls


def test_joint_review_recovers_starting_type_and_never_copies_previous_content():
    req = request(); obj = adjacent(req)
    first = response(req['identity'], kind='uncertain')
    second = response(req['identity']); second['continuation'] = {'status': 'proposed', 'predecessor': obj['identity']}
    second['reviewed_objects'] = [{'identity': obj['identity'], 'table_kind': 'calculation_sheet',
                                  'classification_evidence': [obj['source_text']]}]
    vlm = Provider(first, second)
    out = cp.process_request(req, 'auto', 'auto', vlm, 'current.png', ['previous.png'])
    assert out['table_kind'] == 'calculation_sheet'
    assert out['continuation']['predecessor'] == obj['identity']
    assert out['continuation']['reviewed_objects'][0]['table_kind'] == 'calculation_sheet'
    assert 'previous page' not in json.dumps(out['calculation_sheet'])
    assert vlm.calls[1][0] == ['current.png', 'previous.png']
    assert out['budget']['logical_calls'] == 2


def test_different_table_number_does_not_link_even_when_model_proposes_it():
    req = request(); obj = adjacent(req)
    first = response(req['identity'], kind='uncertain')
    second = response(req['identity'], 'Table 1.3\nPressure')
    second.update(continuation={'status': 'proposed', 'predecessor': obj['identity']},
                  reviewed_objects=[{'identity': obj['identity'], 'table_kind': 'calculation_sheet',
                                     'classification_evidence': [obj['source_text']]}])
    out = cp.process_request(req, 'auto', 'auto', Provider(first, second), 'current', ['prev'])
    assert out['continuation']['status'] == 'conflict'
    assert 'predecessor' not in out['continuation']


def test_context_request_is_pending_without_hidden_retry():
    req = request(); first = response(req['identity'], kind='uncertain'); vlm = Provider(first)
    out = cp.process_request(req, 'auto', 'auto', vlm, 'image')
    assert out['continuation']['reason'] == 'adjacent_context_required'
    assert len(vlm.calls) == 1


def test_joint_review_shares_budget():
    req = request(); adjacent(req); vlm = Provider(response(req['identity'], kind='uncertain'))
    vlm.table_analysis_max_model_calls = 1
    out = cp.process_request(req, 'auto', 'auto', vlm, 'image', ['previous'])
    assert out['continuation']['reason'] == 'table_analysis_budget_exhausted'
    assert len(vlm.calls) == 1


def test_incomplete_items_do_not_change_manual_type():
    req = request(); value = response(req['identity']); value['sections'] = []
    out = cp.process_request(req, 'calculation_sheet', 'reextract', Provider(value), 'image')
    assert out['table_kind'] == 'calculation_sheet'
    assert out['calculation_sheet']['validation_status'] == 'unresolved'


@pytest.mark.parametrize('error', [TimeoutError('secret body'), ValueError('secret body'), RuntimeError('secret body')])
def test_provider_failure_preserves_identity_type_content_and_hides_body(error, capsys):
    req = request(); out = cp.process_request(req, 'calculation_sheet', 'organize_existing', Provider(error))
    assert out['status'] == 'failed'
    assert out['reason'] == ('calculation_provider_timeout' if isinstance(error, TimeoutError) else 'calculation_provider_failed')
    assert out['calculation_identity'] == req['identity']
    assert out['items'][0]['existing_content'] == req['existing_content']
    assert out['table_kind'] == 'calculation_sheet'
    assert 'secret body' not in json.dumps(out) + str(capsys.readouterr())


def test_foreign_response_is_not_applied():
    req = request(); value = response({**req['identity'], 'layout_id': 'foreign'})
    out = cp.process_request(req, 'calculation_sheet', 'reextract', Provider(value), 'image')
    assert out['reason'] == 'calculation_identity_mismatch'
    assert 'calculation_sheet' not in out


def test_organizer_cannot_change_source():
    req = request(); out = cp.process_request(req, 'calculation_sheet', 'organize_existing',
                                            Provider(response(req['identity'])))
    assert out['reason'] == 'calculation_source_rewritten'


def test_cancellation_is_not_converted_to_success():
    with pytest.raises(asyncio.CancelledError):
        cp.process_request(request(), 'calculation_sheet', 'organize_existing', Provider(asyncio.CancelledError()))


def test_text_processing_wire_contains_no_images(monkeypatch):
    client = DynamicVLMClient(None); seen = []
    monkeypatch.setattr(client, '_call_text_prompt', lambda prompt, **kw: seen.append((prompt, kw)) or '{}')
    monkeypatch.setattr(client, '_call_image_prompt', lambda *a, **kw: pytest.fail('image access'))
    client.extract_calculation_sheet(None, {'processing_mode': 'organize_existing', 'table_kind_hint': 'calculation_sheet'})
    assert seen[0][1]['safe_errors'] is True


def test_registered_tool_forwards_processing_contract(monkeypatch):
    captured = []
    monkeypatch.setattr(server, 'extract_page_tables_direct', lambda **kw: captured.append(kw) or '{}')
    asyncio.run(server.extract_page_tables(**fixture()['request']))
    assert captured[0]['processing_mode'] == 'organize_existing'
    assert captured[0]['context'] == fixture()['request']['context']


def test_image_rpc_does_not_scan_neighbors_and_retains_image_hash(monkeypatch, tmp_path):
    image_path = tmp_path/'object.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10)); pix.clear_with(255); pix.save(image_path)
    req = request(); vlm = Provider(response(req['identity']))
    monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: vlm)
    monkeypatch.setattr(sp, '_extract_tables', lambda *a, **k: pytest.fail('whole page scan'))
    out = json.loads(sp.extract_page_tables_direct(file_data=base64.b64encode(image_path.read_bytes()).decode(),
        input_type='image', table_kind_hint='calculation_sheet', processing_mode='reextract',
        context={'object_crop': True, 'calculation_request': req}))
    assert out['status'] == 'needs_review'
    assert len(out['calculation_source']['image_sha256']) == 64
    assert len(out['items']) == 1


def test_disabled_descriptions_do_not_add_calls(monkeypatch):
    monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: pytest.fail('provider construction'))
    args = fixture()['request']; args['describe'] = False
    out = json.loads(sp.extract_page_tables_direct(**args))
    assert out['reason'] == 'classification_not_run'


def test_forward_context_can_recover_start_and_propose_next_page_link():
    req = request(); obj = adjacent(req, 1)
    first = response(req['identity'], kind='uncertain'); second = response(req['identity'])
    second['reviewed_objects'] = [{'identity': obj['identity'], 'table_kind': 'calculation_sheet',
        'classification_evidence': [obj['source_text']],
        'continuation': {'status': 'proposed', 'predecessor': req['identity']}}]
    out = cp.process_request(req, 'auto', 'auto', Provider(first, second), 'start', ['following'])
    assert out['table_kind'] == 'calculation_sheet'
    assert out['continuation']['status'] == 'none'
    assert out['continuation']['reviewed_objects'][0]['continuation']['predecessor'] == req['identity']


@pytest.mark.parametrize('mutation', ['self', 'foreign', 'duplicate'])
def test_untrusted_joint_identity_fails_closed(mutation):
    req = request(); obj = adjacent(req)
    second = response(req['identity'])
    target = req['identity'] if mutation == 'self' else {**obj['identity'], 'table_pk': 'foreign'}
    second['reviewed_objects'] = [{'identity': target, 'table_kind': 'calculation_sheet'}]
    if mutation == 'duplicate':
        second['reviewed_objects'] = [{'identity': obj['identity']}, {'identity': obj['identity']}]
    out = cp.process_request(req, 'auto', 'auto', Provider(response(req['identity'], kind='uncertain'), second), 'image', ['prev'])
    assert out['status'] == 'failed'
    assert out['reason'] == 'continuation_identity_mismatch'


def test_ordinary_formula_lookup_stays_on_grid_path(monkeypatch):
    req = request(); text = '| Type | Formula |\n| --- | --- |\n| A | F=pA |'
    req['existing_content'] = text
    vlm = Provider(response(req['identity'], text, 'data_table'))
    monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: vlm)
    out = json.loads(sp.extract_page_tables_direct(processing_mode='organize_existing', table_kind_hint='data_table',
                    context={'calculation_request': req}))
    assert out['table_kind'] == 'data_table'
    assert out['normalized_rows'] == [['A', 'F=pA']]
    assert 'calculation_sheet' not in out
    assert out.get('lookup_status') != 'unavailable'


def test_intentional_blank_and_original_precision_are_preserved():
    for text, value in [('Pressure p = MPa', ''), ('Pressure p = 1.230 MPa', '1.230')]:
        req = request(); req['existing_content'] = text
        raw = response(req['identity'], text); raw['sections'][0]['items'][0]['value'] = value
        out = cp.process_request(req, 'calculation_sheet', 'organize_existing', Provider(raw))
        assert out['calculation_sheet']['validation_status'] == 'source_validated'
        assert out['calculation_sheet']['sections'][0]['items'][0]['value'] == value
        assert out['calculation_sheet']['unmapped_character_count'] == 0


def test_text_model_cannot_invent_image_geometry():
    req = request(); raw = response(req['identity'], req['existing_content'])
    raw['sections'][0]['items'][0]['bbox'] = [0.1, 0.1, 0.4, 0.4]
    out = cp.process_request(req, 'calculation_sheet', 'organize_existing', Provider(raw))
    source = out['calculation_sheet']['sections'][0]['items'][0]['source']
    assert source['location_scope'] == 'source_text'
    assert 'bbox' not in source


def test_invalid_adjacent_image_is_rejected_before_model(monkeypatch, tmp_path):
    img = tmp_path/'object.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 5, 5)); pix.clear_with(255); pix.save(img)
    req = request(); obj = adjacent(req); obj['image_data'] = 'not base64'
    vlm = Provider(); monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: vlm)
    out = json.loads(sp.extract_page_tables_direct(file_path=str(img), input_type='image',
        table_kind_hint='calculation_sheet', processing_mode='reextract',
        context={'object_crop': True, 'calculation_request': req}))
    assert out['reason'] == 'adjacent_image_invalid'
    assert not vlm.calls


def test_real_client_multi_image_wire_is_bounded_and_ordered(monkeypatch, tmp_path):
    paths = []
    for color in (0, 255):
        path = tmp_path/f'{color}.png'
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 5, 5)); pix.clear_with(color); pix.save(path)
        paths.append(str(path))
    client = DynamicVLMClient(None); captured = []
    monkeypatch.setattr(client, 'ensure_enabled', lambda: None)
    monkeypatch.setattr(client, '_chat_completion_with_stream_fallback',
                        lambda **kw: captured.append(kw) or ('{}', 'non_stream', 'stop'))
    client.extract_calculation_sheet(paths, {'processing_mode': 'auto'})
    parts = captured[0]['messages'][0]['content']
    assert len(parts) == 3
    assert parts[1]['image_url']['url'].endswith(base64.b64encode(Path(paths[0]).read_bytes()).decode())
    assert parts[2]['image_url']['url'].endswith(base64.b64encode(Path(paths[1]).read_bytes()).decode())
    with pytest.raises(ValueError, match='image_budget_exceeded'):
        client._call_image_prompt(paths*2, 'data', 1)


def test_full_pdf_hash_mismatch_fails_before_model(monkeypatch, tmp_path):
    path = tmp_path/'source.pdf'
    with fitz.open() as doc:
        doc.new_page(); doc.save(path)
    req = request(); req['identity']['page_no'] = 1; req['bbox'] = [0, 0, 1, 1]
    vlm = Provider(); monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: vlm)
    out = json.loads(sp.extract_page_tables_direct(file_path=str(path), page_no=1,
        table_kind_hint='calculation_sheet', processing_mode='reextract', context={'calculation_request': req}))
    assert out['reason'] == 'calculation_identity_mismatch'
    assert not vlm.calls


def test_legacy_classification_provider_failure_is_object_diagnostic():
    from tests.test_pdf2md_enhanced_upload_semantics import pp
    class Failed:
        def extract_region_structured(self, *args, **kwargs):
            raise RuntimeError('private model response')
    payload = {'tables': [{'markdown': 'Pressure p = MPa'}]}
    pp._enrich_upload_semantics(Failed(), 'image', {}, payload, True)
    assert payload['tables'][0]['table_kind'] == 'uncertain'
    assert payload['tables'][0]['table_classification']['reason'] == 'calculation_provider_failed'


def test_legacy_image_classification_error_logs_do_not_contain_response(monkeypatch, tmp_path, caplog):
    path = tmp_path/'image.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 5, 5)); pix.clear_with(255); pix.save(path)
    client = DynamicVLMClient(None); client.max_retries = 0
    monkeypatch.setattr(client, 'ensure_enabled', lambda: None)
    def fail(**kwargs):
        assert kwargs['safe_errors'] is True
        raise RuntimeError('private model response')
    monkeypatch.setattr(client, '_chat_completion_with_stream_fallback', fail)
    with pytest.raises(RuntimeError, match='model_call_failed'):
        client.extract_region_structured(str(path), [{'type': 'table'}])
    assert 'private model response' not in caplog.text


def test_generic_model_cannot_claim_manual_origin_or_trusted_identity():
    from tests.test_pdf2md_enhanced_upload_semantics import pp
    raw = {'markdown': 'Pressure', 'table_kind': 'uncertain', 'table_classification': {},
           'table_kind_source': 'manual', 'calculation_identity': request()['identity'],
           'continuation': {'status': 'proposed', 'predecessor': request()['identity']}}
    structured = pp._normalize_structured({'tables': [raw]})
    metadata = next(iter(structured['table_metadata'].values()))
    assert 'calculation_identity' not in metadata
    assert metadata['table_kind_source'] == 'automatic'
    assert metadata['continuation'] == {'status': 'pending', 'reason': 'adjacent_context_required'}


@pytest.mark.parametrize('kind', ['server_error', 'token_correction', 'redirect'])
def test_processing_physical_http_guard_counts_fallbacks_and_redirects(monkeypatch, kind):
    import httpx
    import openai
    sent = []
    def handle(req):
        sent.append(req)
        if kind == 'redirect':
            return httpx.Response(307, headers={'location': '/redirected'})
        if kind == 'token_correction':
            return httpx.Response(400, json={'error': {'message': 'Range of max_tokens should be [1, 4]'}})
        return httpx.Response(503, json={'error': {'message': 'unavailable'}})
    monkeypatch.setattr(openai, 'DefaultHttpxClient',
                        lambda **kw: httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True, **kw))
    client = DynamicVLMClient({'model': 'synthetic', 'api_key': 'synthetic', 'base_url': 'https://synthetic.invalid',
        '_calculation_processing': True, 'table_analysis_max_physical_requests': 1, 'max_retries': 9})
    try:
        assert client._client.max_retries == 0
        assert client.max_retries == 0
        with pytest.raises(RuntimeError, match='table_analysis_physical_budget_exhausted'):
            client._call_text_prompt('synthetic', 10, safe_errors=True)
        assert len(sent) == 1
        assert client.physical_requests == 1
        # A subsequent logical call cannot reset the HTTP budget.
        with pytest.raises(RuntimeError, match='table_analysis_physical_budget_exhausted'):
            client._call_text_prompt('synthetic', 10, safe_errors=True)
        assert len(sent) == 1
    finally:
        client._client.close()


def test_processing_rpc_reports_physical_exhaustion_without_discarding_content(monkeypatch):
    import httpx
    import openai
    clients = []
    def http_client(**kwargs):
        client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503)), **kwargs)
        clients.append(client)
        return client
    monkeypatch.setattr(openai, 'DefaultHttpxClient', http_client)
    try:
        out = json.loads(sp.extract_page_tables_direct(**fixture()['request'], vlm_config={
            'model': 'synthetic', 'api_key': 'synthetic', 'base_url': 'https://synthetic.invalid',
            'table_analysis_max_physical_requests': 1}))
        assert out['reason'] == 'table_analysis_physical_budget_exhausted'
        assert out['budget']['physical_requests'] == 1
        assert out['budget']['physical_request_limit'] == 1
        assert out['budget']['sdk_retries'] == 0
        assert out['table_kind'] == 'calculation_sheet'
        assert out['items'][0]['existing_content'] == request()['existing_content']
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize('mode,logical,expected', [('organize_existing', 2, 2), ('auto', 8, 4), ('reextract', 1, 2)])
def test_processing_default_physical_cap_is_bounded(mode, logical, expected):
    client = DynamicVLMClient({'_calculation_processing': mode, 'table_analysis_max_model_calls': logical})
    assert client.physical_request_limit == expected
    legacy = DynamicVLMClient(None)
    assert legacy.physical_request_limit is None


def test_zero_physical_budget_never_prepares_image(monkeypatch):
    args = fixture()['request']; args['processing_mode'] = 'reextract'
    monkeypatch.setattr(sp, '_prepare_context', lambda *a, **k: pytest.fail('must not prepare image'))
    out = json.loads(sp.extract_page_tables_direct(**args, vlm_config={'table_analysis_max_physical_requests': 0}))
    assert out['reason'] == 'table_analysis_physical_budget_exhausted'
    assert out['budget']['logical_calls'] == out['budget']['physical_requests'] == 0


@pytest.mark.parametrize('limit', [-1, True, '2', 5])
def test_physical_budget_cannot_exceed_processing_cap(limit):
    out = json.loads(sp.extract_page_tables_direct(**fixture()['request'],
                    vlm_config={'table_analysis_max_physical_requests': limit}))
    assert out['reason'] == 'invalid_physical_model_budget'

@pytest.mark.parametrize('content', [
    '<table><tr><td>Pressure</td><td>p = \\frac{F}{A} &amp; q</td></tr></table>',
    '| Pressure | p = \\frac{F}{A} |\n| --- | --- |',
    '  Pressure p = \\frac{F}{A}\n\n  Blank =   ',
])
def test_organizer_uses_one_citation_text_and_preserves_raw_source(content):
    req = request(); req['existing_content'] = content
    text = cp.source_context(content)['text']
    vlm = Provider(response(req['identity'], text))
    out = cp.process_request(req, 'calculation_sheet', 'organize_existing', vlm)
    assert out['status'] == 'needs_review'
    assert vlm.calls[0][1]['source_text'] == text
    assert out['calculation_source']['original_content'] == content
    assert out['calculation_sheet']['source_text'] == text
    assert len(out['calculation_sheet']['sections'][0]['items']) == 1


def test_organizer_rejects_changes_to_citation_text_without_retry():
    req = request(); req['existing_content'] = '<table><td>Pressure</td></table>'
    vlm = Provider(response(req['identity'], 'Pressure changed'))
    out = cp.process_request(req, 'calculation_sheet', 'organize_existing', vlm)
    assert out['reason'] == 'calculation_source_rewritten'
    assert len(vlm.calls) == 1


def test_empty_html_organization_does_not_call_provider():
    req = request(); req['existing_content'] = '<table><tr><td> </td></tr></table>'
    vlm = Provider()
    out = cp.process_request(req, 'calculation_sheet', 'organize_existing', vlm)
    assert out['reason'] == 'calculation_source_missing'
    assert not vlm.calls
