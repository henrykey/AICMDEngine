"""Raster-only calculation boundaries preserve conditions, margins and reading order."""
import importlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image, ImageDraw
from tests.test_pdf2md_calculation_processing import cp
b = importlib.import_module(cp.__package__ + '.calculation_blocks')


def image_fixture(tmp_path):
    path = tmp_path / 'scan.png'
    image = Image.new('RGB', (600, 800), 'white')
    draw = ImageDraw.Draw(image)
    for y, text in [(60, 'Calculation'), (130, 'a = b + c'), (180, 'if b > 0'),
                    (360, 'd = e / f'), (390, '+ g / h'), (440, 'for f > 0'), (700, 'Note: use SI')]:
        draw.text((55, y), text, fill='black')
    image.save(path)
    return path


def test_scanned_sections_cover_full_object_in_order(tmp_path):
    path = image_fixture(tmp_path)
    regions = [{'bbox': [.1,.15,.8,.25]}, {'bbox': [.1,.44,.8,.58]}]
    boxes = b.calculation_block_boxes(regions, [.05,.05,.95,.95])
    assert len(boxes) == 2
    assert boxes[0][1] == .05 and boxes[-1][3] == .95
    assert boxes[0][3] == boxes[1][1]
    assert all(box[0] == .05 and box[2] == .95 for box in boxes)


@pytest.mark.parametrize('regions', [[], [{'bbox':[0,0,1,1]}],
    [{'bbox':[.1,.1,.9,.6]}, {'bbox':[.1,.5,.9,.8]}],
    [{'bbox':[.1,.1,.9,.3]}, {'bbox':[.1,.4,float('nan'),.8]}]])
def test_unreliable_regions_do_not_claim_blocks(regions):
    assert b.calculation_block_boxes(regions, [0,0,1,1]) == []


def test_crop_layout_maps_back_to_page_and_preserves_failed_source(tmp_path):
    path = image_fixture(tmp_path)
    class Ocr:
        enabled = True
        use_layout_parsing = True
        def parse_layout(self, crop):
            width,height = Image.open(crop).size
            return {'data_info': {'width': width,'height':height}, 'layout_details': [[
                {'label':'formula','bbox_2d':[0,100,width,150],'content':'$a=b+c$'},
                {'label':'text','bbox_2d':[0,160,width,190],'content':'if b > 0'},
                {'label':'formula','bbox_2d':[0,300,width,350],'content':'$d=e/f$'},
                {'label':'text','bbox_2d':[0,360,width,400],'content':'for f > 0'}]]}
        def extract_page(self, crop):
            raise TimeoutError()
    text, manifest = b.transcribe_calculation_blocks(str(path), [.05,.05,.95,.95], Ocr(), tmp_path/'crops', blocks=[[.05,.05,.95,.35], [.05,.35,.95,.95]], engine='ocr')
    assert text is None
    assert manifest['reason'] == 'block_transcription_failed'
    assert manifest['blocks'][0]['bbox'][1] == .05
    assert manifest['logical_calls'] == 1


def test_success_preserves_multiline_formula_conditions_and_notes(tmp_path):
    path = image_fixture(tmp_path)
    calls = []
    class Ocr:
        def extract_page(self, image):
            calls.append(Image.open(image).size)
            return SimpleNamespace(markdown=['标题\n$a=b+c$\n条件 b>0',
                '$d=\\frac{e}{f}+\\frac{g}{h}$\n条件 f>0\n注：SI'][len(calls)-1], page_text='')
    layout = [{'type':'formula','bbox':[.1,.15,.8,.22]},
              {'type':'text','bbox':[.1,.23,.8,.28]},
              {'type':'formula','bbox':[.1,.44,.8,.52]},
              {'type':'text','bbox':[.1,.54,.8,.89]}]
    text, manifest = b.transcribe_calculation_blocks(str(path), [.05,.05,.95,.95], Ocr(), tmp_path/'blocks', blocks=b.calculation_block_boxes(b._formula_sections(layout, [.05,.05,.95,.95]), [.05,.05,.95,.95]), engine='ocr')
    assert manifest['status'] == 'complete'
    assert manifest['layout_calls'] == 0 and manifest['logical_calls'] == 2
    assert text == '标题\n$a=b+c$\n条件 b>0\n\n$d=\\frac{e}{f}+\\frac{g}{h}$\n条件 f>0\n注：SI'
    assert sum(height for width,height in calls) >= 720


def test_missed_ink_at_section_boundary_keeps_whole_source(tmp_path):
    path = tmp_path / 'missed.png'
    image = Image.new('RGB', (600,800), 'white')
    ImageDraw.Draw(image).rectangle((60,350,530,370), fill='black')
    image.save(path)
    class Ocr:
        def extract_page(self, path):
            raise AssertionError('unsafe crops must not be sent to OCR')
    layout = [{'type':'formula','bbox':[.1,.2,.9,.3]}, {'type':'formula','bbox':[.1,.6,.9,.7]}]
    text, manifest = b.transcribe_calculation_blocks(str(path), [0,0,1,1], Ocr(), tmp_path/'blocks', blocks=b.calculation_block_boxes(b._formula_sections(layout, [0,0,1,1]), [0,0,1,1]), engine='ocr')
    assert text is None and manifest['reason'] == 'block_boundary_intersects_content'
    assert manifest['logical_calls'] == 0


def test_crop_error_keeps_whole_source(monkeypatch, tmp_path):
    path = image_fixture(tmp_path)
    pp = importlib.import_module(cp.__package__ + '.page_processor')
    def failed(*args, **kwargs): raise ValueError('invalid image')
    monkeypatch.setattr(pp, '_crop_layout_block_image', failed)
    text, manifest = b.transcribe_calculation_blocks(str(path), [0,0,1,1], object(), tmp_path/'blocks', blocks=[[0,0,1,1]], engine='ocr')
    assert text is None and manifest['reason'] == 'block_transcription_failed'
    assert manifest['logical_calls'] == 0


@pytest.mark.parametrize('automatic', [False, True])
def test_blocks_share_physical_budget_and_never_exceed_explicit_cap(tmp_path, automatic):
    from tests.test_pdf2md_calculation_processing import DynamicVLMClient
    path = image_fixture(tmp_path)
    client = DynamicVLMClient(None if automatic else {'table_analysis_max_physical_requests': 1})
    calls = []
    class Ocr:
        use_layout_parsing = False
        def extract_page(self, crop):
            self.request_guard(None)
            calls.append(crop)
            return SimpleNamespace(markdown='$x=1$', page_text='')
    layout = [{'type':'formula','bbox':[.1,.15,.8,.28]}, {'type':'formula','bbox':[.1,.44,.8,.89]}]
    with client.calculation_scope():
        text, manifest = b.transcribe_calculation_blocks(str(path), [.05,.05,.95,.95],
                b.BudgetedCalculationOcr(Ocr(), client), tmp_path/'budget', blocks=b.calculation_block_boxes(b._formula_sections(layout, [.05,.05,.95,.95]), [.05,.05,.95,.95]), engine='ocr')
    assert client.physical_requests == len(calls) == (2 if automatic else 1)
    if automatic:
        assert text == '$x=1$\n\n$x=1$'
        assert manifest['status'] == 'complete'
    else:
        assert client.physical_request_limit == 1
        assert text is None
        assert manifest['status'] == 'failed'
        assert manifest['blocks'][0]['text'] == '$x=1$'


@pytest.mark.parametrize('limit', [1, 2])
def test_ocr_budget_counts_real_http_redirects_before_sending(tmp_path, limit, monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from tests.test_pdf2md_calculation_processing import DynamicVLMClient
    OcrClient = importlib.import_module(cp.__package__ + '.ocr_clients.openai_compatible_ocr_client').OpenAICompatibleOcrClient
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            received.append('POST')
            self.send_response(302); self.send_header('Location', '/final'); self.end_headers()
        def do_GET(self):
            received.append('GET')
            body = json.dumps({'layout_details': []}).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    client = DynamicVLMClient({'table_analysis_max_physical_requests': limit})
    ocr = OcrClient({'enabled': True, 'model': 'glm-ocr', 'base_url': f'http://127.0.0.1:{server.server_port}', 'max_retries': 0})
    try:
        with client.calculation_scope():
            operation = lambda: b.BudgetedCalculationOcr(ocr, client).parse_layout(str(image_fixture(tmp_path)))
            if limit == 1:
                with pytest.raises(Exception): operation()
            else:
                assert operation() == {'layout_details': []}
        assert received == (['POST'] if limit == 1 else ['POST', 'GET'])
        assert client.physical_requests == limit
        assert ocr.request_guard is None
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_two_columns_partition_without_losing_margins():
    regions = [{'bbox':[.1,.1,.9,.2]}, {'bbox':[.1,.4,.45,.8]}, {'bbox':[.55,.4,.9,.8]}]
    boxes = b.calculation_block_boxes(regions, [0,0,1,1])
    assert len(boxes) == 3
    assert sum((x[2]-x[0])*(x[3]-x[1]) for x in boxes) == pytest.approx(1)
    assert boxes[1][2] == boxes[2][0]


def test_declared_thousand_coordinates_normalized():
    response = {'coordinate_space':'normalized_1000', 'object_bbox':[100,100,900,900],
                'sections':[{'bbox':[100,100,900,300]}, {'bbox':[100,400,900,900]}]}
    box, sections = b.normalize_calculation_regions(response, (600,800))
    assert box == [.1,.1,.9,.9]
    assert sections[0]['bbox'] == [.1,.1,.9,.3]
    response['coordinate_space'] = 'unknown'
    with pytest.raises(ValueError): b.normalize_calculation_regions(response, (600,800))


def test_outer_boundary_detects_cut_formula_but_not_thin_rule(tmp_path):
    image = Image.new('RGB', (600,800), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((100,390,180,410), fill='black')
    assert b.boundary_intersects_content(image, [0,0,1,.5])
    image = Image.new('RGB', (600,800), 'white')
    ImageDraw.Draw(image).line((0,400,600,400), fill='black', width=2)
    assert not b.boundary_intersects_content(image, [0,0,1,.5])


def test_clipped_object_is_rejected_without_relocation(tmp_path):
    path = tmp_path / 'clipped.png'
    image = Image.new('RGB', (600,800), 'white')
    ImageDraw.Draw(image).rectangle((100,390,180,410), fill='black')
    image.save(path)
    class Vlm:
        enabled = True
        def calculation_sections(self, *args, **kwargs): pytest.fail('no implicit relocation')
        def transcribe_calculation_block(self, *args, **kwargs): pytest.fail('unsafe block')
    text, manifest = b.transcribe_calculation_blocks(str(path), [0,0,1,.5], object(), tmp_path/'out',
        blocks=[[0,0,1,.5]], engine='vlm', vlm=Vlm())
    assert text is None
    assert manifest['reason'] == 'block_boundary_intersects_content'
    assert manifest['vlm_calls'] == 0


@pytest.mark.parametrize('space,box', [('normalized',[.1,.1,.9,.9]), ('pixels',[60,80,540,720])])
def test_explicit_coordinate_units(space,box):
    result,_=b.normalize_calculation_regions({'coordinate_space':space,'object_bbox':box,'sections':[]},(600,800))
    assert result == [.1,.1,.9,.9]


def test_vlm_truncation_is_not_accepted_as_complete(monkeypatch):
    from tests.test_pdf2md_calculation_processing import DynamicVLMClient
    client=DynamicVLMClient(None)
    def incomplete(*args,**kwargs):
        client.last_call_info={'truncated':True}
        return '$x='
    monkeypatch.setattr(client,'_call_image_prompt',incomplete)
    with pytest.raises(ValueError,match='block_response_truncated'):
        client.transcribe_calculation_block('unused.png')
    with pytest.raises(ValueError,match='section_response_truncated'):
        client.calculation_sections('unused.png',[0,0,1,1])


def test_good_ocr_layout_is_used_without_vlm_layout_call(tmp_path):
    path=image_fixture(tmp_path)
    class Vlm:
        enabled=True
        def reserve_automatic_calculation_calls(self,n): pass
        def calculation_sections(self,*args,**kwargs):
            raise AssertionError('reliable OCR layout must be reused')
        def transcribe_calculation_block(self,path, **kwargs):return '$x=1$'
    layout=[{'type':'formula','bbox':[.1,.15,.8,.28]}, {'type':'formula','bbox':[.1,.44,.8,.89]}]
    text,manifest=b.transcribe_calculation_blocks(str(path),[.05,.05,.95,.95],object(),tmp_path/'out',blocks=b.calculation_block_boxes(b._formula_sections(layout, [.05,.05,.95,.95]), [.05,.05,.95,.95]),engine='vlm',vlm=Vlm())
    assert manifest['status']=='complete' and manifest['layout_source']=='caller'
    assert manifest['vlm_calls']==2 and manifest['layout_calls']==0


def test_vlm_block_failure_preserves_partial_evidence_and_falls_back(tmp_path):
    path=image_fixture(tmp_path)
    class Vlm:
        enabled=True
        calls=0
        def reserve_automatic_calculation_calls(self,n): pass
        def transcribe_calculation_block(self,path, **kwargs):
            self.calls+=1
            if self.calls==2:raise TimeoutError()
            return '$x=1$'
    layout=[{'type':'formula','bbox':[.1,.15,.8,.28]}, {'type':'formula','bbox':[.1,.44,.8,.89]}]
    text,manifest=b.transcribe_calculation_blocks(str(path),[.05,.05,.95,.95],object(),tmp_path/'out',blocks=b.calculation_block_boxes(b._formula_sections(layout, [.05,.05,.95,.95]), [.05,.05,.95,.95]),engine='vlm',vlm=Vlm())
    assert text is None and manifest['reason']=='block_transcription_failed'
    assert manifest['blocks'][0]['text']=='$x=1$'
    assert manifest['blocks'][1]['error_type']=='TimeoutError'



def test_vlm_block_preserves_markdown_and_latex_without_json_escaping(monkeypatch):
    from tests.test_pdf2md_calculation_processing import DynamicVLMClient
    client=DynamicVLMClient(None)
    monkeypatch.setattr(client,'_call_image_prompt',lambda *a,**k:'```markdown\nChecks\n\n$S_{bo}$\n```')
    assert client.transcribe_calculation_block('unused.png') == 'Checks\n\n$S_{bo}$'



def test_touching_regions_are_not_overlapping():
    regions=[{'bbox':[0,0,1,.5]}, {'bbox':[0,.5,1,1]}]
    assert b.calculation_block_boxes(regions,[0,0,1,1]) == [[0,0,1,.5],[0,.5,1,1]]


def test_unsafe_internal_split_returns_control_without_whole_fallback(tmp_path):
    path = tmp_path / 'internal.png'
    image = Image.new('RGB', (600,800), 'white')
    ImageDraw.Draw(image).rectangle((60,390,530,410), fill='black')
    image.save(path)
    class Vlm:
        enabled = True
        def calculation_sections(self, *args, **kwargs): pytest.fail('no implicit layout')
        def transcribe_calculation_block(self, *args, **kwargs): pytest.fail('no whole fallback')
    text, manifest = b.transcribe_calculation_blocks(str(path), [0,0,1,1], object(), tmp_path/'blocks',
        blocks=[[0,0,1,.5], [0,.5,1,1]], engine='vlm', vlm=Vlm())
    assert text is None
    assert manifest['reason'] == 'block_boundary_intersects_content'
    assert manifest['vlm_calls'] == 0


def test_section_prompt_uses_one_coordinate_scale_for_target_and_response(monkeypatch):
    from tests.test_pdf2md_calculation_processing import DynamicVLMClient
    client = DynamicVLMClient(None)
    prompts = []
    def call(image, prompt, **kwargs):
        prompts.append(prompt)
        return '{"coordinate_space":"normalized_1000","object_bbox":[100,200,900,800],"sections":[]}'
    monkeypatch.setattr(client, '_call_image_prompt', call)
    result = client.calculation_sections('unused.png', [.1, .2, .9, .8])
    assert '[100.0, 200.0, 900.0, 800.0]' in prompts[0]
    assert 'normalized 0-1' not in prompts[0]
    assert result['object_bbox'] == [100, 200, 900, 800]


def test_block_transcription_supplies_object_context_without_duplicating_rows(monkeypatch):
    from tests.test_pdf2md_calculation_processing import DynamicVLMClient
    client = DynamicVLMClient(None)
    calls = []
    monkeypatch.setattr(client, '_call_image_prompt', lambda paths, prompt, **kwargs: calls.append((paths, prompt)) or '$x=1$')
    assert client.transcribe_calculation_block('block.png', logical_reorder=True, context_image='object.png') == '$x=1$'
    paths, prompt = calls[0]
    assert paths == ['block.png', 'object.png']
    assert 'Only transcribe rows visible in the FIRST image' in prompt
    assert 'SECOND image' in prompt and 'column' in prompt


def test_each_block_receives_same_complete_object_context(tmp_path):
    path = image_fixture(tmp_path)
    calls = []
    class Vlm:
        enabled = True
        def reserve_automatic_calculation_calls(self, n): pass
        def transcribe_calculation_block(self, crop, logical_reorder=False, context_image=None):
            calls.append((Image.open(crop).size, Image.open(context_image).size if context_image else None, logical_reorder))
            return '$x=1$'
    layout = [{'type':'formula','bbox':[.1,.15,.8,.28]}, {'type':'formula','bbox':[.1,.44,.8,.89]}]
    _, manifest = b.transcribe_calculation_blocks(str(path), [.05,.05,.95,.95], object(), tmp_path/'out', blocks=b.calculation_block_boxes(b._formula_sections(layout, [.05,.05,.95,.95]), [.05,.05,.95,.95]), engine='vlm', vlm=Vlm())
    assert manifest['status'] == 'complete'
    assert len(calls) == 2
    assert all(context == (540,720) and logical for crop, context, logical in calls)
    assert all(crop[1] < context[1] for crop, context, logical in calls)


def test_recovery_uses_review_evidence_as_untrusted_comparison_data(monkeypatch):
    from tests.test_pdf2md_calculation_processing import DynamicVLMClient
    client = DynamicVLMClient(None)
    calls = []
    monkeypatch.setattr(client, '_call_image_prompt', lambda paths, prompt, **kwargs: calls.append(prompt) or '$x$')
    client.transcribe_calculation_block('block.png', logical_reorder=True, context_image='object.png',
                                       review_evidence=['missing superscript'])
    assert 'missing superscript' in calls[0]
    assert 'Verify these observations against pixels' in calls[0]
    assert 'Start with the exact table title' not in calls[0]
