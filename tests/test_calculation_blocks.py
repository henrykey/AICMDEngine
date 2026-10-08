import importlib
import fitz
from tests.test_pdf2md_calculation_processing import cp
b = importlib.import_module(cp.__package__ + '.calculation_blocks')


def page_fixture():
    doc=fitz.open(); page=doc.new_page(width=600,height=800)
    for y in (80,94,250,264,450,464,700):
        page.draw_line((50,y),(550,y))
    for y, text in [(90,'First formula section'),(150,'a = b + c'),(260,'Second formula section'),
                    (350,'d = e'),(460,'Third formula section'),(600,'f = g')]:
        page.insert_text((65,y),text,fontsize=8)
    return doc,page


def test_automatic_boxes_cover_entire_object_without_gaps():
    doc,page=page_fixture();bbox=[.075,.07,.925,.9]
    boxes=b.calculation_block_boxes(page,bbox)
    assert len(boxes)==3
    assert boxes[0][1]==bbox[1] and boxes[-1][3]==bbox[3]
    assert all(a[3]==c[1] for a,c in zip(boxes,boxes[1:]))
    assert all(x[0]==bbox[0] and x[2]==bbox[2] for x in boxes)


def test_no_text_or_invalid_geometry_does_not_guess_blocks():
    d=fitz.open();p=d.new_page()
    assert b.calculation_block_boxes(p,[0,0,1,1])==[]
    assert b.calculation_block_boxes(p,[0,0,float('nan'),1])==[]


def test_failed_block_does_not_replace_existing_source(tmp_path):
    doc,page=page_fixture();image=tmp_path/'page.png';page.get_pixmap(dpi=300).save(image)
    class Ocr:
        def extract_page(self,path): raise TimeoutError()
    content,manifest=b.transcribe_calculation_blocks(page,str(image),[.075,.07,.925,.9],Ocr(),tmp_path)
    assert content is None and manifest['reason']=='block_transcription_failed'
    assert manifest['logical_calls']==1


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
