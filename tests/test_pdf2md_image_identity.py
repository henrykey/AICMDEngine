"""Image task provenance must retain document identity independently of image hashes."""
import base64
import hashlib
import json
from pathlib import Path
import pytest
from PIL import Image
from tests.test_pdf2md_enhanced_task_manager import TaskManager


def identity(**changes):
    return dict(tenant_id='6', doc_id='document', version=3, run_id='run-a', source_page_no=17,
                source_file_sha256='a'*64, render_dpi=300, **changes)


def test_task_and_source_snapshot_keep_original_scope_and_image_provenance(tmp_path):
    path=tmp_path/'page.png';Image.new('RGB',(120,180),'white').save(path)
    manager=TaskManager(str(tmp_path/'output'))
    scope=identity()
    task=manager.start_task('page', file_data=base64.b64encode(path.read_bytes()).decode(), source_identity=scope)
    scope['version']=99
    assert task.source_identity['version']==3
    assert task.input_image['width']==120 and task.input_image['height']==180
    assert task.input_image['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    artifact=manager.save_calculation_source(task.task_id,1,'tables:0',{'layout_id':'p17-o001-table'},'$x=1$')
    assert artifact['source_identity']['source_page_no']==17
    assert artifact['source_identity']['source_file_sha256']=='a'*64
    assert artifact['input_image']==task.input_image
    saved=json.loads((tmp_path/'output/tasks'/task.task_id/'task.json').read_text())
    assert saved['source_identity']==task.source_identity
    for field,value in [('tenant_id','7'),('doc_id','other'),('version',4),('run_id','run-b'),('source_page_no',18)]:
        bad={**task.source_identity,field:value}
        with pytest.raises(ValueError,match='task_source_identity_mismatch'):
            manager.validate_source_identity(task.task_id,bad)
    with pytest.raises(ValueError,match='task_source_identity_mismatch'):
        manager.validate_source_identity(task.task_id,None)
    manager.validate_source_identity(task.task_id,task.source_identity)
    result={'render': {'markdown': 'Plain page'}, 'rag': {'elements': {}}, 'source_identity': {'tenant_id': 'wrong'}}
    manager.update_page_result(task.task_id,1,result)
    assert result['source_identity']==task.source_identity
    assert result['input_image']==task.input_image
    saved=json.loads((tmp_path/'output/tasks'/task.task_id/'task.json').read_text())
    page=json.loads((tmp_path/'output/tasks'/task.task_id/'page_1.json').read_text())
    assert page['input_image']==task.input_image
    assert page['source_identity']==task.source_identity



@pytest.mark.parametrize('field,value',[('tenant_id',''),('version',0),('source_page_no',True),('source_file_sha256','bad'),('render_dpi',150)])
def test_incomplete_or_invalid_source_identity_fails_before_task_creation(tmp_path,field,value):
    manager=TaskManager(str(tmp_path/'output'))
    bad={**identity(),field:value}
    with pytest.raises(ValueError,match='invalid_source_identity'):
        manager.start_task('page',file_data='invalid',source_identity=bad)
    assert manager._tasks=={}


@pytest.mark.parametrize('tool_name,extra',[
    ('process_task_page',{'page_no':1,'routing_config':{'calculation_async':True,'calculation_poll':True}}),
    ('get_task_status',{}),('retry_failed_pages',{}),('finalize_task',{}),
])
def test_tools_reject_wrong_scope_before_cached_workers_or_task_mutations(tmp_path,monkeypatch,tool_name,extra):
    import asyncio
    from tests.test_pdf2md_enhanced_single_page_tools import server
    path=tmp_path/'page.png';Image.new('RGB',(120,180),'white').save(path)
    manager=TaskManager(str(tmp_path/'output'))
    task=manager.start_task('scoped',file_data=base64.b64encode(path.read_bytes()).decode(),source_identity=identity())
    monkeypatch.setattr(server,'manager',manager)
    tool=getattr(server,tool_name)
    fn=getattr(tool,'fn',tool)
    before=(tmp_path/'output/tasks'/task.task_id/'task.json').read_bytes()
    for scope in [None,{**identity(),'tenant_id':'other'},{**identity(),'version':4}]:
        result=json.loads(asyncio.run(fn(task_id=task.task_id,source_identity=scope,**extra)))
        assert result['error']=='task_source_identity_mismatch'
        assert (tmp_path/'output/tasks'/task.task_id/'task.json').read_bytes()==before


def test_process_rejects_original_page_mismatch_before_starting_worker(tmp_path,monkeypatch):
    import asyncio
    from tests.test_pdf2md_enhanced_single_page_tools import server
    path=tmp_path/'page.png';Image.new('RGB',(120,180),'white').save(path)
    manager=TaskManager(str(tmp_path/'output'))
    task=manager.start_task('scoped',file_data=base64.b64encode(path.read_bytes()).decode(),source_identity=identity())
    monkeypatch.setattr(server,'manager',manager)
    fn=getattr(server.process_task_page,'fn',server.process_task_page)
    result=json.loads(asyncio.run(fn(task_id=task.task_id,page_no=1,source_identity=identity(),routing_config={'source_page_no':18})))
    assert result['error']=='task_source_page_mismatch'
    assert not server._calculation_page_operations.get((task.task_id,1))
