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


@pytest.mark.parametrize('run_pages', [[], [18, 17], [17, 17], [True]])
def test_invalid_document_run_page_set_fails_before_source_read(tmp_path, run_pages):
    manager=TaskManager(str(tmp_path/'output'))
    with pytest.raises(ValueError, match='invalid_source_identity'):
        manager.start_task('page', file_data='invalid', source_identity=identity(run_pages=run_pages))
    assert manager._tasks == {}


def test_finalize_document_run_tool_marks_only_full_page_set_finalized(tmp_path, monkeypatch):
    import asyncio
    from tests.test_pdf2md_enhanced_single_page_tools import server
    path=tmp_path/'page.png';Image.new('RGB',(120,180),'white').save(path)
    manager=TaskManager(str(tmp_path/'output'))
    scope=identity(run_pages=[17])
    task=manager.start_task('document-page-17',file_data=base64.b64encode(path.read_bytes()).decode(),
                            pages=[1],source_identity=scope)
    manager.update_page_result(task.task_id,1,{'render':{'markdown':'ok'}})
    manager.finalize_task(task.task_id)
    monkeypatch.setattr(server,'manager',manager)

    fn=getattr(server.finalize_document_run,'fn',server.finalize_document_run)
    result=json.loads(asyncio.run(fn(task_id=task.task_id,source_identity=scope)))

    assert result['status']=='FINALIZED'
    assert result['run_pages']==[17]
    with pytest.raises(ValueError,match='document_run_already_finalized'):
        manager.start_task('late-page',file_data=base64.b64encode(path.read_bytes()).decode(),
                           pages=[1],source_identity=scope)


def test_closed_document_run_rejects_retry_and_page_processing(tmp_path, monkeypatch):
    import asyncio
    from tests.test_pdf2md_enhanced_single_page_tools import server
    path=tmp_path/'page.png';Image.new('RGB',(120,180),'white').save(path)
    manager=TaskManager(str(tmp_path/'output'))
    scope=identity(run_pages=[17])
    task=manager.start_task('document-page-17',file_data=base64.b64encode(path.read_bytes()).decode(),
                            pages=[1],source_identity=scope)
    manager.update_page_failed(task.task_id,1,'synthetic failure')
    manager.finalize_task(task.task_id)
    assert manager.finalize_document_run(task.task_id,scope)['status']=='FINALIZED'
    monkeypatch.setattr(server,'manager',manager)

    retry_fn=getattr(server.retry_failed_pages,'fn',server.retry_failed_pages)
    retry=json.loads(asyncio.run(retry_fn(task_id=task.task_id,source_identity=scope)))
    assert retry['error']=='document_run_already_finalized'
    process_fn=getattr(server.process_task_page,'fn',server.process_task_page)
    process=json.loads(asyncio.run(process_fn(task_id=task.task_id,page_no=1,source_identity=scope)))
    assert process['error']=='document_run_already_finalized'
    assert manager.get_task(task.task_id).pages[1].status=='FAILED'


def test_timed_out_worker_prevents_document_run_finalization_until_thread_exits(tmp_path, monkeypatch):
    import asyncio
    from threading import Event
    from tests.test_pdf2md_enhanced_single_page_tools import server
    path=tmp_path/'page.png';Image.new('RGB',(120,180),'white').save(path)
    manager=TaskManager(str(tmp_path/'output'))
    scope=identity(run_pages=[17])
    task=manager.start_task('document-page-17',file_data=base64.b64encode(path.read_bytes()).decode(),
                            pages=[1],source_identity=scope)
    started=Event();release=Event()

    def slow_process(*args):
        started.set()
        release.wait(2)
        return {'render': {'markdown': 'late result'}}

    monkeypatch.setattr(server,'manager',manager)
    monkeypatch.setattr(server,'process_page',slow_process)
    monkeypatch.setattr(server,'_resolve_page_timeout',lambda _config: 0.01)
    process_fn=getattr(server.process_task_page,'fn',server.process_task_page)

    async def run():
        response=json.loads(await process_fn(task_id=task.task_id,page_no=1,source_identity=scope))
        assert response['error'].startswith('process_task_page timeout')
        assert started.wait(2)
        assert manager.finalize_document_run(task.task_id,scope)['status']=='INCOMPLETE'
        release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            result=manager.finalize_document_run(task.task_id,scope)
            if result['status']=='FINALIZED':
                return result
        raise AssertionError('timed-out page worker did not exit')

    assert asyncio.run(run())['status']=='FINALIZED'


@pytest.mark.parametrize('tool_name,extra',[
    ('process_task_page',{'page_no':1,'routing_config':{'calculation_async':True,'calculation_poll':True}}),
    ('get_task_status',{}),('retry_failed_pages',{}),('finalize_task',{}),('finalize_document_run',{}),
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
