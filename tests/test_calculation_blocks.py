import importlib
from tests.test_pdf2md_calculation_processing import cp


def test_block_source_persisted_before_structuring(monkeypatch):
    mod=importlib.import_module(cp.__package__+'.calculation_sheet')
    events=[]
    class Provider:
        automatic_calculation_budget=False
        def transcribe_calculation_blocks(self,item):
            events.append('ocr');return '$a=b$',{'status':'complete','reason':None,'logical_calls':2,'blocks':[]}
    def store(ref,item,content):
        assert content=='$a=b$' and item['calculation_source']['origin']=='block_ocr'
        events.append('persist');return {'id':'saved'}
    def structure(vlm,item,content,*args,**kwargs):
        assert item['calculation_source']['artifact']=={'id':'saved'}
        events.append('structure');return 0,None
    monkeypatch.setattr(cp,'structure_calculation_source',structure)
    item={'table_kind':'calculation_sheet'}
    mod.extract_calculation_items(Provider(),'image.png',item,'old OCR','tables:0',source_store=store)
    assert events==['ocr','persist','structure']


def test_unexpected_block_failure_preserves_original_ocr_before_structuring(monkeypatch):
    mod=importlib.import_module(cp.__package__+'.calculation_sheet')
    events=[]
    class Provider:
        automatic_calculation_budget=False
        def transcribe_calculation_blocks(self,item):
            raise OSError('synthetic crop directory failure')
    def store(ref,item,content):
        assert content=='original OCR'
        events.append('persist')
        return {'id':'saved-original'}
    def structure(vlm,item,content,*args,**kwargs):
        assert content=='original OCR'
        assert item['calculation_source']['artifact']=={'id':'saved-original'}
        events.append('structure')
        return 0,None
    monkeypatch.setattr(cp,'structure_calculation_source',structure)
    item={'table_kind':'calculation_sheet'}
    mod.extract_calculation_items(Provider(),'image.png',item,'original OCR','tables:0',source_store=store)
    assert events==['persist','structure']
    assert item['calculation_source']['block_transcription']['status']=='fallback'
