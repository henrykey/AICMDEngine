"""Remaining plan contracts; synthetic sources and stubbed providers only."""
import importlib
import json
import pytest
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools as sp
from tests.test_pdf2md_enhanced_table_query import request, run


def test_pandas_origin_mapping_without_cell_closing_tags():
    grid, meta=sp._html_table_to_grid('<table><thead><tr><td>Code<td>Load</thead><tbody><tr><td>001<td> 1  2 </tbody></table>')
    assert grid==[['Code','Load'],['001','1 2']]
    assert meta['grid_parser']=='pandas_lxml_source_tokens'
    assert meta['source_cells'][2]['raw_text']=='001'
    assert meta['source_cells'][3]['raw_text']==' 1  2 '


def test_pandas_blank_repeated_merged_origins():
    grid,meta=sp._html_table_to_grid('<table><tr><th>A</th><th>B</th></tr><tr><td rowspan="2">001</td><td></td></tr><tr><td>001</td></tr></table>')
    assert grid==[['A','B'],['001',''],['001','001']]
    assert meta['grid_parser']=='pandas_lxml_source_tokens'
    assert meta['cell_status'][-2]['source_row']==1


def test_tilde_label_diagnostic_exact_lookup_never_range_execution():
    q=importlib.import_module(sp.__package__+'.table_query')
    out=run(request('<table><tr><th>Band</th><th>Value</th></tr><tr><td>150~475</td><td>9</td></tr></table>'))['query_enhancement']
    result=q.select_candidate_labels(out,'section_1',{'c0':'150~475'})
    assert result['status']=='diagnostic_only'
    assert result['records'][0]['values']['c1']['raw_text']=='9'
    assert q.select_candidate_labels(out,'section_1',{'c0':200})['records']==[]
    with pytest.raises(ValueError): q.select_records(out,'section_1',{'c0':200})


def test_explicit_missing_parent_recovery_is_crop_only(tmp_path, monkeypatch):
    import fitz,hashlib
    path=tmp_path/'page.png';pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),False);pix.clear_with(255);pix.save(str(path))
    calls=[]
    class VLM:
        enabled=True
        def __init__(self,cfg): self.last_object_call_info={}; assert cfg['description_language']=='en'
        def extract_table_html(self,path,block,compact=False):
            image=fitz.Pixmap(path);calls.append((image.width,image.height,block['layout_id']))
            return '<table><tr><td>$$Q=KA$$</td><td>9</td></tr></table>'
    monkeypatch.setattr(sp,'DynamicVLMClient',VLM)
    target={'layout_id':'missing-parent','type':'table','bbox':[.1,.1,.5,.5],'bbox_space':'normalized_page','page_no':1,'source_sha1':hashlib.sha1(path.read_bytes()).hexdigest()}
    out=json.loads(sp.extract_page_tables_direct(file_path=str(path),input_type='image',description_language='en',context={'structure_target':target}))
    assert calls==[(40,40,'missing-parent')]
    assert out['tables'][0]['layout_id']=='missing-parent'
    assert '$$Q=KA$$' in out['tables'][0]['markdown']
    assert out['model_calls']=={'glm_ocr':0,'vlm_ocr':1}
    assert out['structure_recovery']['status']=='complete'


def test_wrong_target_source_does_not_construct_provider(tmp_path,monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import PNG_DATA
    import base64
    path=tmp_path/'p.png';path.write_bytes(base64.b64decode(PNG_DATA))
    monkeypatch.setattr(sp,'DynamicVLMClient',lambda cfg:pytest.fail('no provider before source binding'))
    target={'layout_id':'t','type':'table','bbox':[0,0,1,1],'bbox_space':'normalized_page','page_no':1,'source_sha1':'wrong'}
    out=json.loads(sp.extract_page_tables_direct(file_path=str(path),input_type='image',context={'structure_target':target}))
    assert out['structure_recovery']['reason']=='structure_target_source_mismatch'
    assert out['model_calls']=={'glm_ocr':0,'vlm_ocr':0}


def test_cell_images_do_not_require_page_level_figure(tmp_path):
    import fitz
    pp=importlib.import_module(sp.__package__+'.page_processor')
    path=tmp_path/'page.png';pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),False);pix.clear_with(255);pix.save(str(path))
    data={'tables':[{'layout_id':'parent','bbox':[0,0,1,1],'bbox_space':'normalized_page','markdown':'unchanged',
      'source_cells':[{'row':0,'col':0,'bbox':[0,0,.5,1],'bbox_space':'normalized_page','image_regions':[
      {'image_id':'diagram','bbox':[.1,.1,.4,.4],'bbox_space':'normalized_page'}]}]}],'figures':[]}
    pp._attach_figure_assets(path,data,1)
    assert len(data['figures'])==1
    figure=data['figures'][0]
    assert figure['image_asset']['status']=='available'
    assert figure['parent_relation']['cell_source']=='r0c0'
    assert figure['parent_relation']['table_layout_id']=='parent'
    assert data['tables'][0]['markdown']=='unchanged'
    pp._attach_figure_assets(path,data,1)
    assert len(data['figures'])==1


def test_chinese_title_does_not_hide_english_description():
    language=importlib.import_module(sp.__package__+'.semantic_language')
    assert language.description_mismatch('传热计算公式：Calculates the heat transfer coefficient from the temperature difference.', 'zh')


def test_declared_cell_image_cannot_bind_to_another_cell(tmp_path):
    import fitz
    pp=importlib.import_module(sp.__package__+'.page_processor')
    path=tmp_path/'p.png';p=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,10,10),False);p.clear_with(255);p.save(str(path))
    data={'tables':[{'layout_id':'t','bbox':[0,0,1,1],'bbox_space':'normalized_page','source_cells':[
      {'row':0,'col':0,'bbox':[0,0,.5,1],'bbox_space':'normalized_page','image_regions':[{'image_id':'i','bbox':[.6,.1,.9,.9],'bbox_space':'normalized_page'}]},
      {'row':0,'col':1,'bbox':[.5,0,1,1],'bbox_space':'normalized_page'}]}], 'figures':[]}
    pp._attach_figure_assets(path,data,1)
    assert data['figures'][0]['parent_relation']['status']=='unresolved'
    assert data['figures'][0]['parent_relation']['reason']=='cell_image_geometry_conflict'
    assert data['figures'][0]['image_asset']['status']=='unresolved'


def test_omitted_tags_do_not_drop_escaped_comparisons():
    grid,meta=sp._html_table_to_grid('<table><tr><td>A<td>B<tr><td>x &lt; y &gt; z<td>001</table>')
    assert grid[1]==['x < y > z','001']


def test_all_td_semantic_interpretation_is_source_only(monkeypatch):
    from tests.test_pdf2md_enhanced_single_page_tools import DynamicVLMClient
    markup='<table><tr><td>Code</td><td>Pressure</td></tr><tr><td>001</td><td>9</td></tr><tr><td>002</td><td>12</td></tr></table>'
    req=request(markup);req.update(query_strategy='model_required',max_model_calls=1)
    def explain(self,payload,language):
        return {'binding':payload['binding'],'lookup_sections':[{'key':'s','fields':[{'key':'code','header_path':['r0c0']},{'key':'pressure','header_path':['r0c1']}],
          'records':[{'values':{'code':f'r{r}c0','pressure':f'r{r}c1'}} for r in (1,2)]}],'unresolved':[]}
    monkeypatch.setattr(DynamicVLMClient,'explain_table_query',explain)
    out=run(req)['query_enhancement']
    assert out['lookup_status']=='complete' and out['model_calls']==1
    q=importlib.import_module(sp.__package__+'.table_query')
    assert q.select_records(out,'s',{'code':'001'})[0]['values']['pressure']['raw_text']=='9'


def test_structure_recovery_budget_exhaustion_has_no_hidden_retry(tmp_path,monkeypatch):
    import fitz,hashlib
    path=tmp_path/'p.png';p=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);p.clear_with(255);p.save(str(path))
    calls=[]
    class VLM:
        enabled=True
        def __init__(self,cfg): self.last_object_call_info={}
        def extract_table_html(self,*a,**k): calls.append(1);return '<table><tr><td>incomplete'
    monkeypatch.setattr(sp,'DynamicVLMClient',VLM)
    target={'layout_id':'t','type':'table','bbox':[0,0,1,1],'bbox_space':'normalized_page','page_no':1,'source_sha1':hashlib.sha1(path.read_bytes()).hexdigest(),'max_model_calls':1}
    out=json.loads(sp.extract_page_tables_direct(file_path=str(path),input_type='image',context={'structure_target':target}))
    assert len(calls)==1 and out['model_calls']['vlm_ocr']==1
    assert out['structure_recovery']['status']=='unresolved' and out['tables']==[]
    assert out['structure_recovery']['diagnostics']['objects'][0]['reason']=='model_budget_exhausted'


@pytest.mark.parametrize('dockerfile',['Dockerfile','Dockerfile.cn'])
def test_packaged_query_executes_pandas_without_checkout(tmp_path,dockerfile):
    import shlex,shutil,subprocess,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'mcp/servers/PDF2MDEnhanced'
    package=tmp_path/'PDF2MDEnhanced';package.mkdir()
    for line in (root/dockerfile).read_text().splitlines():
        if line.startswith('COPY ') and line.endswith(' /app/PDF2MDEnhanced/'):
            for source in shlex.split(line)[1:-1]:shutil.copy2(root/source,package/source)
    shutil.copytree(root/'ocr_clients',package/'ocr_clients')
    result=subprocess.run([sys.executable,'-I','-c',
       'import sys;sys.path.insert(0,sys.argv[1]);from PDF2MDEnhanced.single_page_tools import _html_table_to_grid;'
       'assert _html_table_to_grid("<table><tr><td>001</td></tr></table>")[0]==[["001"]]',str(tmp_path)],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'pandas>=2.2.3,<3' in (root/'requirements.txt').read_text()
    assert 'lxml==6.1.1' in (root/'requirements.txt').read_text()


def test_automatic_header_query_comparator_uses_projected_headers():
    from scripts.audit_pdf2md_content_quality import verify_queries
    markup='<table><thead><tr><td>Code</td><td>Load</td></tr></thead><tr><td>001</td><td>9</td></tr></table>'
    out=run(request(markup))['query_enhancement'];grid,_=sp._html_table_to_grid(markup)
    spec={'header_rows':[0],'data_start':1,'data_stop':2,'row_key_col':0,'cases':[{'where':{'row_label':'001','header_1':'Load'},'expected_values':['9']}]}
    assert verify_queries(grid,out,spec)==[{'case':1,'manual_passed':True,'automatic_status':'passed'}]


def test_rowspan_zero_respects_row_group_with_caption():
    grid,meta=sp._html_table_to_grid('<table><caption>Data</caption><tr><td rowspan="0">001</td><td>2</td></tr><tr><td>3</td></tr></table>')
    assert grid==[['001','2'],['001','3']]


def test_text_outside_cells_is_not_silently_covered():
    out=run(request('<table>Only dry operation<tr><th>A</th></tr><tr><td>9</td></tr></table>'))['query_enhancement']
    assert out['lookup_status']=='unavailable'
    assert any(c['text']=='Only dry operation' for c in out['source_cells'].values())


def test_rectangular_expansion_budget_precedes_pandas(monkeypatch):
    import pandas
    monkeypatch.setattr(pandas,'read_html',lambda *a,**k:pytest.fail('must reject before rectangular allocation'))
    markup='<table><tr>'+('<td colspan="100">x</td>'*10)+'</tr>'+('<tr><td>x</td></tr>'*500)+'</table>'
    with pytest.raises(ValueError,match='input_budget_exceeded'):
        sp._html_table_to_grid(markup)


def test_embedded_formulas_bind_exact_cells_without_duplicate_objects():
    pp=importlib.import_module(sp.__package__+'.page_processor')
    markup='<table><tr><td>$$Q=KA$$</td><td>$$F=ma \\tag{2}$$</td></tr></table>'
    payload={'layout_id':'parent','markdown':markup,'bbox':[0,0,1,1],'bbox_space':'normalized_page'}
    out=pp._build_layout_output_elements('',{'tables':[payload]},'full_glm_ocr','en')
    formulas=out['tables'][0]['contained_formulas']
    assert [f['cell_source'] for f in formulas]==['r0c0','r0c1']
    assert formulas[0]['latex']=='$$Q=KA$$'
    assert formulas[0]['formula_no']=='' and formulas[1]['formula_no']=='2'
    assert formulas[0]['formula_name']=='' and formulas[0]['semantic_status']=='missing'
    assert out['formulas']==[] and out['tables'][0]['markdown']==markup
    for formula in formulas:
        assert formula['parent_table_layout_id']=='parent'
        assert formula['source_field']=='raw_html'
