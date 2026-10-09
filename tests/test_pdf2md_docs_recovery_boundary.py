"""Docs selects recovery operations; single tools preserve source and return control."""
import json
from types import SimpleNamespace
import pytest
from tests.test_pdf2md_calculation_processing import sp, request, DynamicVLMClient
from tests.test_pdf2md_enhanced_single_page_tools import PNG_DATA


@pytest.mark.parametrize('source', [
    '<table><tr><td>$S$</td></tr></table>',
    '<table><tr><td>A</td></tr><tr><td>B</td><td>C</td></tr></table>',
])
def test_whole_transcription_never_starts_quality_model_or_block_recovery(monkeypatch, source):
    client = DynamicVLMClient(None)
    client.enabled = True
    monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: client)
    def forbidden(*args, **kwargs):
        pytest.fail('Docs did not request another model or recovery operation')
    monkeypatch.setattr(client, 'extract_region_structured', forbidden)
    monkeypatch.setattr(client, 'calculation_sections', forbidden)
    monkeypatch.setattr(client, 'transcribe_calculation_block', forbidden)
    calls = []
    class OCR:
        enabled = True
        use_layout_parsing = False
        def __init__(self, config, **kwargs):
            assert config['max_retries'] == 0
        def extract_page(self, image):
            self.request_guard(None)
            calls.append(image)
            return SimpleNamespace(markdown=source, page_text='')
    monkeypatch.setattr(sp, 'OpenAICompatibleOcrClient', OCR)
    req = request()
    req['stage'] = 'transcription'
    out = json.loads(sp.extract_page_tables_direct(file_data=PNG_DATA, input_type='image',
        table_kind_hint='calculation_sheet', processing_mode='reextract',
        context={'object_crop': True, 'calculation_request': req, 'transcription_engine': 'ocr'}))
    assert out['status'] == 'needs_review'
    assert out['calculation_source']['original_content'] == source
    assert 'calculation_sheet' not in out
    assert len(calls) == 1
    assert out['model_calls'] == {'glm_ocr': 1, 'vlm_ocr': 0}
    assert out['budget']['physical_requests'] == 1

@pytest.mark.parametrize('engine', ['ocr', 'vlm'])
def test_explicit_block_keeps_exact_scope_and_selected_engine(tmp_path, engine):
    from PIL import Image
    import importlib
    block_tool = importlib.import_module(sp.__package__ + '.calculation_blocks')
    path = tmp_path / 'page.png'
    Image.new('RGB', (100, 100), 'white').save(path)
    calls = []
    class OCR:
        def extract_page(self, image):
            calls.append(('ocr', Image.open(image).size))
            return SimpleNamespace(markdown='$x=1$\nif p>0', page_text='')
        def parse_layout(self, *args):
            pytest.fail('layout was not requested')
    class VLM:
        enabled = True
        def reserve_automatic_calculation_calls(self, count):
            assert count == 1
        def transcribe_calculation_block(self, image, **kwargs):
            calls.append(('vlm', Image.open(image).size))
            return '$x=1$\nif p>0'
        def calculation_sections(self, *args, **kwargs):
            pytest.fail('block selection belongs to Docs')
    selected = [.1, .2, .9, .6]
    text, manifest = block_tool.transcribe_calculation_blocks(str(path), [0, 0, 1, 1], OCR(), tmp_path/'out',
        blocks=[selected], engine=engine, vlm=VLM())
    assert text == '$x=1$\nif p>0'
    assert calls == [(engine, (80, 40))]
    assert manifest['effective_bbox'] == [0, 0, 1, 1]
    assert manifest['blocks'][0]['bbox'] == selected
    assert manifest['layout_calls'] == 0


def test_missing_block_selection_returns_without_model_calls(tmp_path):
    import importlib
    block_tool = importlib.import_module(sp.__package__ + '.calculation_blocks')
    text, manifest = block_tool.transcribe_calculation_blocks('unused.png', [0, 0, 1, 1], object(), tmp_path,
        engine='ocr')
    assert text is None
    assert manifest['reason'] == 'explicit_blocks_required'
    assert manifest['logical_calls'] == manifest['vlm_calls'] == 0


def test_explicit_block_request_flows_through_existing_table_tool(monkeypatch):
    import importlib
    block_tool = importlib.import_module(sp.__package__ + '.calculation_blocks')
    client = DynamicVLMClient(None)
    client.enabled = True
    monkeypatch.setattr(sp, 'DynamicVLMClient', lambda *_: client)
    selected = [[0, 0, 1, .5]]
    def blocks(image, bbox, ocr, directory, **kwargs):
        assert kwargs['blocks'] == selected
        assert kwargs['engine'] == 'vlm'
        return '$x=1$\nCondition A', {'status': 'complete', 'blocks': [{'bbox': selected[0]}],
                                    'logical_calls': 0, 'vlm_calls': 1}
    monkeypatch.setattr(block_tool, 'transcribe_calculation_blocks', blocks)
    monkeypatch.setattr(client, 'extract_calculation_sheet', lambda *args: pytest.fail('whole object not requested'))
    req = request()
    req.update(stage='transcription', blocks=selected)
    out = json.loads(sp.extract_page_tables_direct(file_data=PNG_DATA, input_type='image',
        table_kind_hint='calculation_sheet', processing_mode='reextract',
        context={'object_crop': True, 'calculation_request': req, 'transcription_engine': 'vlm',
                 'calculation_transcription_mode': 'blocks'}))
    assert out['status'] == 'needs_review'
    assert out['calculation_source']['original_content'] == '$x=1$\nCondition A'
    assert out['model_calls'] == {'glm_ocr': 0, 'vlm_ocr': 1}
    assert out['budget']['logical_calls'] == 1
    assert out['calculation_source']['pipeline']['transcription']['engine'] == 'vlm'


def test_layout_tool_returns_bound_partition_without_transcribing_blocks(monkeypatch, tmp_path):
    from PIL import Image
    import hashlib
    path = tmp_path / 'object.png'
    Image.new('RGB', (100, 100), 'white').save(path)
    calls = []
    class OCR:
        enabled = True
        def __init__(self, config, **kwargs):
            assert config['max_retries'] == 0
        def parse_layout(self, image, **kwargs):
            self.request_guard(None)
            calls.append(image)
            return {'data_info': {'width': 100, 'height': 100}, 'layout_details': [[
                {'label': 'formula', 'bbox_2d': [10,10,90,25], 'content': 'a=b+c'},
                {'label': 'text', 'bbox_2d': [10,26,90,35], 'content': 'if b>0'},
                {'label': 'formula', 'bbox_2d': [10,60,90,75], 'content': 'd=e/f'},
                {'label': 'text', 'bbox_2d': [10,76,90,85], 'content': 'if f>0'},
            ]]}
    monkeypatch.setattr(sp, 'OpenAICompatibleOcrClient', OCR)
    result = json.loads(sp.analyze_page_layout_direct(file_path=str(path), input_type='image',
        routing_config={'calculation_block_candidates': True}))
    assert len(calls) == 1
    assert result['image_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['candidate_blocks'] == [[0,0,1,.475], [0,.475,1,1]]
    assert result['candidate_bbox_space'] == 'normalized_object'
    assert result['physical_requests'] == 1


def test_generic_table_metadata_never_starts_calculation_processing(monkeypatch):
    calls = []
    class VLM:
        enabled = True
        max_tokens = 4096
        def _call_image_prompt(self, *args, **kwargs):
            return json.dumps({'tables': [{'index': 0, 'description': 'Input values used in the design.'}]})
    monkeypatch.setattr(sp, 'complete_calculation_batch', lambda *a, **k: calls.append('calculation') or 0, raising=False)
    items = [{'markdown': '| Input | Value |\n| --- | --- |\n| p | 12 |'}]
    counts = {'vlm_ocr': 0}
    sp._enrich_table_metadata_with_vlm(SimpleNamespace(image_path='unused', page_text=''),
        VLM(), items, True, counts, [], 'en')
    assert counts['vlm_ocr'] == 1
    assert calls == []
