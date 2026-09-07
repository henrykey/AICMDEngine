"""Synthetic, offline generic content-quality regressions."""
import importlib
import json
import pytest
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools as sp
from tests.test_pdf2md_object_semantics import request

sem = importlib.import_module(sp.__package__ + '.object_semantics')
pp = importlib.import_module(sp.__package__ + '.page_processor')

@pytest.mark.parametrize('language,text', [('en', 'Heat transfer：这是根据温度计算传热系数的公式。'), ('zh', 'Calculates the heat transfer coefficient from temperature.')])
def test_wrong_language_rejected_once(language, text):
    class Provider:
        calls = 0
        def _call_text_prompt(self, *a, **k):
            self.calls += 1
            return json.dumps({'formulas': [{'element_id': 'o1', 'semantic_desc': text}]})
    p = Provider()
    result = sem.enhance_object_semantics({**request(), 'document_language': language, 'request_id': 'r'}, provider_factory=lambda c: p)
    assert result['status'] == 'failed'
    assert result['reason'] == 'description_language_mismatch'
    assert result['request_id'] == 'r'
    assert result['quality']['unresolved_fields'] == ['semantic_desc']
    assert p.calls == 1


def test_partial_fields_keep_valid_source_name():
    class Provider:
        def _call_text_prompt(self, *a, **k):
            return json.dumps({'formulas': [{'element_id': 'o1', 'formula_name': 'Q = KA', 'semantic_desc': '这是计算传热系数的公式说明。'}]})
    result = sem.enhance_object_semantics({**request(), 'document_language': 'en', 'missing_fields': ['formula_name', 'semantic_desc']}, provider_factory=lambda c: Provider())
    assert result['status'] == 'complete'
    assert result['repairs']['formulas'][0]['semantic_desc'] == ''
    assert result['quality']['unresolved_fields'] == ['semantic_desc']


def test_upload_wrong_language_retains_structure():
    item = {'latex': 'Q=KA'}
    pp._set_object_semantics(item, {'formula_name': 'Q', 'description': '这是计算传热系数的公式说明。'}, 'formula_name', 'en')
    assert item['latex'] == 'Q=KA'
    assert item['description'] == ''
    assert item['semantic_status'] != 'complete'
    assert item['semantic_reason'] == 'description_language_mismatch'


def test_empty_grid_rows_keep_source_coordinates():
    grid, meta = sp._html_table_to_grid('<table><tr><th>A</th></tr><tr><td></td></tr><tr><td>001</td></tr></table>')
    assert grid == [['A'], [''], ['001']]
    assert meta['source_cells'][2]['row'] == 2

from tests.test_pdf2md_enhanced_table_query import request as table_request, run


def test_explicit_thead_td_automatic_projection():
    markup = '<table><thead><tr><td>Code</td><td>Limit</td></tr></thead><tbody><tr><td>001</td><td>9</td></tr></tbody></table>'
    result = run(table_request(markup))['query_enhancement']
    assert result['lookup_status'] == 'complete'
    assert result['lookup_sections'][0]['rows'] == [['001', '9']]


@pytest.mark.parametrize('body,reason', [('<tr><td colspan="2">Group A</td></tr>', 'body_spanning_cells'), ('<tr><td>Note: only cold</td><td>3</td></tr>', 'conditional_source_requires_review')])
def test_specific_table_blockers(body, reason):
    markup = '<table><tr><th>A</th><th>B</th></tr>' + body + '</table>'
    out = run(table_request(markup))['query_enhancement']
    assert reason in [x['reason'] for x in out['unresolved']]
    assert out['lookup_sections'] == []


def test_raw_cell_whitespace_and_markup_preserved():
    _, meta = sp._html_table_to_grid('<table><tr><td> 001  X <b>bold</b> </td></tr></table>')
    assert meta['source_cells'][0]['raw_html'] == ' 001  X <b>bold</b> '
    assert meta['source_cells'][0]['raw_text'] == ' 001  X bold '

ledger = importlib.import_module(sp.__package__ + '.layout_ledger')
from tests.test_pdf2md_enhanced_bad_text_policy import _layout_raw


def test_complete_html_classified_as_parent_table_not_formula():
    markup = '<table><tr><td>$$Q=KA$$</td><td>9</td></tr></table>'
    outcome = ledger.build_layout_outcome(_layout_raw([{'label': 'formula', 'bbox_2d': [10,10,90,90], 'content': markup}]), page_no=3, fallback_width=100, fallback_height=100)
    assert len(outcome['payloads']['tables']) == 1
    assert outcome['payloads']['formulas'] == []
    assert outcome['payloads']['tables'][0]['markdown'] == markup


def relation_payload():
    return {'tables': [{'layout_id': 't', 'bbox': [0,0,1,1], 'bbox_space': 'normalized_page', 'source_cells': [{'row': 0, 'col': 0, 'rowspan': 2, 'colspan': 1, 'bbox': [0,0,.5,1], 'bbox_space': 'normalized_page'}]}], 'formulas': [{'layout_id': 'f', 'bbox': [.1,.1,.2,.2], 'bbox_space': 'normalized_page', 'latex': 'Q=KA', 'formula_no': '(3)'}], 'figures': []}


def test_parent_and_merged_cell_relation_preserves_formula():
    data = relation_payload()
    ledger.attach_object_relationships(data, 7)
    child = data['formulas'][0]
    assert child['parent_relation']['table_layout_id'] == 't'
    assert child['parent_relation']['cell_source'] == 'r0c0'
    assert child['parent_relation']['page_no'] == 7
    assert child['latex'] == 'Q=KA' and child['formula_no'] == '(3)'


def test_ambiguous_parent_never_guessed():
    data = relation_payload(); data['tables'].append({**data['tables'][0], 'layout_id': 't2'})
    ledger.attach_object_relationships(data, 7)
    assert data['formulas'][0]['parent_relation']['reason'] == 'ambiguous_parent_table'
    assert 'table_layout_id' not in data['formulas'][0]['parent_relation']


def test_figure_bytes_and_exact_crop_no_temp_leak(tmp_path):
    import fitz, base64
    path = tmp_path / 'source.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0,0,100,100), False); pix.clear_with(255); pix.save(str(path))
    data = relation_payload(); data['figures'] = [{'layout_id': 'image', 'bbox': [.1,.1,.3,.4], 'bbox_space': 'normalized_page'}]
    ledger.attach_object_relationships(data, 7)
    before = list(tmp_path.iterdir())
    pp._attach_figure_assets(path, data, 7)
    asset = data['figures'][0]['image_asset']
    decoded = fitz.Pixmap(base64.b64decode(asset['data'].split(',',1)[1]))
    assert (decoded.width, decoded.height) == (20,30)
    assert asset['page_no'] == 7 and asset['status'] == 'available'
    assert data['figures'][0]['parent_relation']['cell_source'] == 'r0c0'
    assert list(tmp_path.iterdir()) == before
    pp._attach_figure_assets(path, data, 7)
    assert data['figures'][0]['image_asset'] == asset


@pytest.mark.parametrize('bbox', [[-1,0,.5,.5], [0,0,float('nan'),1], [0,0,2,1], None])
def test_invalid_figure_geometry_never_reads_path(bbox):
    data={'figures':[{'layout_id':'i', 'bbox':bbox, 'bbox_space':'normalized_page'}]}
    pp._attach_figure_assets('/never/read', data, 1)
    assert data['figures'][0]['image_asset']['reason'] == 'unreliable_image_bbox'


def test_caption_is_covered_or_unresolved():
    out = run(table_request('<table><caption>Only dry service</caption><tr><th>A</th></tr><tr><td>9</td></tr></table>'))['query_enhancement']
    assert out['lookup_status'] == 'unavailable'
    assert any(c['text'] == 'Only dry service' for c in out['source_cells'].values())


def test_figure_page_rejects_wrong_language(monkeypatch):
    monkeypatch.setattr(sp, "_source_payload", lambda ctx: {})
    ctx = sp.SinglePageContext(input_type='image', source_path='page.png', image_path='page.png', page_no=1, description_language='en')
    out = sp._figure_page_result(ctx, {'vlm_ocr':1}, [], '', [{'description':'这是描述设备内部结构关系的示意图。'}])
    assert out['items'][0]['description'] == ''
    assert out['items'][0]['semantic_reason'] == 'description_language_mismatch'


def test_no_cell_geometry_does_not_guess_from_row_order():
    data = relation_payload(); data['tables'][0]['source_cells'] = []
    ledger.attach_object_relationships(data, 7)
    assert data['formulas'][0]['parent_relation']['reason'] == 'missing_cell_geometry'


def test_resource_failure_is_bounded():
    data = {'figures':[{'layout_id':'i','bbox':[0,0,1,1],'bbox_space':'normalized_page'}]}
    pp._attach_figure_assets('/nonexistent-private-file',data,1)
    assert data['figures'][0]['image_asset']['reason'] == 'image_asset_generation_failed'
    assert '/nonexistent' not in str(data)


@pytest.mark.parametrize('language,text', [('en','Calculates heat transfer for alloy 316L at 20 °C.'), ('zh','根据温差计算材料 316L 的传热系数。'), ('en','Q = K A'), ('zh','σ = F/A')])
def test_language_valid_prose_and_short_symbols(language,text):
    assert not importlib.import_module(sp.__package__+'.semantic_language').description_mismatch(text, language)


def test_asset_and_relation_survive_output_normalization(tmp_path):
    import fitz
    path = tmp_path / 'page.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0,0,30,30),False); pix.clear_with(255); pix.save(str(path))
    data = relation_payload()
    data['figures']=[{'layout_id':'i','bbox':[.1,.1,.3,.4],'bbox_space':'normalized_page','description':'Shows two connected pipes.'}]
    ledger.attach_object_relationships(data, 2)
    pp._attach_figure_assets(path, data, 2)
    output = pp._build_layout_output_elements('',data,'full_glm_ocr','en')
    assert output['figures'][0]['image_asset']['data'].startswith('data:image/png;base64,')
    assert output['figures'][0]['parent_relation']['cell_source']=='r0c0'


def test_multitable_multiimage_unique_cell_binding():
    data = relation_payload()
    data['tables'][0]['bbox']=[0,0,.5,1]
    data['tables'].append({'layout_id':'right','bbox':[.5,0,1,1],'bbox_space':'normalized_page','source_cells':[{'row':0,'col':0,'bbox':[.5,0,1,1],'bbox_space':'normalized_page'}]})
    data['figures']=[{'layout_id':'left-image','bbox':[.1,.1,.2,.2],'bbox_space':'normalized_page'}, {'layout_id':'right-image','bbox':[.6,.1,.8,.2],'bbox_space':'normalized_page'}]
    ledger.attach_object_relationships(data, 2)
    assert [i['parent_relation']['table_layout_id'] for i in data['figures']]==['t','right']


def test_missing_continuation_returns_dependency_and_zero_calls():
    req=table_request();req['requires_previous_context']=True
    out=run(req)['query_enhancement']
    assert out['dependencies'][0]['auto_fetch'] is False
    assert out['dependencies'][0]['binding']['table_id']==req['target']['table_id']
    assert out['model_calls']==0


def test_copied_source_title_does_not_invalidate_english_prose():
    language=importlib.import_module(sp.__package__+'.semantic_language')
    item={'title':'中文引用标题','description':'Describes the pressure limit for this material.', 'semantic_summary':'中文引用标题: Describes the pressure limit for this material.'}
    assert language.validate_descriptions(item,'en')==[]


def test_figure_asset_count_budget(tmp_path):
    import fitz
    path=tmp_path/'page.png';pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,10,10),False);pix.clear_with(255);pix.save(str(path))
    data={'figures':[{'layout_id':str(i),'bbox':[0,0,1,1],'bbox_space':'normalized_page'} for i in range(33)]}
    pp._attach_figure_assets(path,data,1)
    assert all(i['image_asset']['status']=='available' for i in data['figures'][:32])
    assert data['figures'][32]['image_asset']['reason']=='image_asset_budget_exceeded'


@pytest.mark.parametrize('markup,reason', [('<table><tr></tr></table>','table_structure_unavailable'), ('<table><tr><th>A</th></tr><tfoot><tr><td>9</td></tr></tfoot></table>','footer_requires_review'), ('<table><tr><th>A</th></tr><tr><td><img src="file:///private/image.png"></td></tr></table>','embedded_image_requires_asset')])
def test_no_silent_noncell_or_image_coverage(markup,reason):
    out=run(table_request(markup))['query_enhancement']
    assert out['lookup_status']=='unavailable'
    assert reason in [i['reason'] for i in out['unresolved']]
    assert out['model_calls']==0


def test_layout_enhanced_language_contract():
    import inspect
    assert 'description_language' in inspect.signature(sp.extract_page_layout_enhanced_direct).parameters
    prompt=sp._prompt_layout_figures([], '', 'en')
    assert 'MUST be written in English' in prompt


def test_recovery_preserves_language_failure_reason():
    payload=pp._object_success_payload({'type':'formula','layout_id':'f'}, {'latex':'Q=KA','description':'','semantic_reason':'description_language_mismatch','missing_fields':['description']})
    assert payload['semantic_reason']=='description_language_mismatch'
    out=pp._build_layout_output_elements('',{'formulas':[payload]},'full_glm_ocr','en')
    assert out['formulas'][0]['semantic_reason']=='description_language_mismatch'
