"""The task lifecycle accepts page PNGs without a PDF text/geometry dependency."""
import base64
from pathlib import Path
from PIL import Image
from tests.test_pdf2md_enhanced_bad_text_policy import page_processor as pp, TaskManager


def test_png_task_keeps_pixels_and_uses_image_layout(monkeypatch, tmp_path):
    path = tmp_path / 'input.png'
    Image.new('RGB', (420, 600), 'white').save(path)
    manager = TaskManager(str(tmp_path / 'tasks'))
    task = manager.start_task('image-page', file_data=base64.b64encode(path.read_bytes()).decode())
    assert task.total_pages == 1
    assert Path(task.source_path).suffix == '.png'
    def forbidden(*args, **kwargs):
        raise AssertionError('image entry must not inspect PDF text or vector geometry')
    monkeypatch.setattr(pp, '_collect_metrics', forbidden)
    monkeypatch.setattr(pp, '_detect_bad_text', forbidden)
    class Ocr:
        enabled = True
        use_layout_parsing = True
        def __init__(self, *a, **k): pass
        def parse_layout(self, image):
            assert Image.open(image).size == (420, 600)
            assert Path(image).read_bytes() == path.read_bytes()
            return {'md_results': 'Synthetic content', 'layout_details': [[
                {'label': 'text', 'bbox_2d': [42, 60, 378, 540], 'content': 'Synthetic content'}]]}
    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', Ocr)
    result = pp.process_page(task.source_path, 1, 'auto', {'enabled': False}, {
        'source_page_no': 17, 'render_dpi': 300, 'render_cleanup_with_llm': False,
        'vlm_ocr_enabled': False, 'ocr_config': {'glm_ocr': {'enabled': True}}}, None)
    assert result['layout_status'] == 'EXTRACTED'
    assert result['layout'][0]['layout_id'].startswith('p17-')
    assert result['layout'][0]['bbox'] == [.1, .1, .9, .9]


def test_missing_layout_never_reports_complete_even_with_usable_text(monkeypatch, tmp_path):
    from types import SimpleNamespace
    path = tmp_path / 'input.png'
    Image.new('RGB', (420, 600), 'white').save(path)
    class Ocr:
        enabled = True
        use_layout_parsing = False
        def __init__(self, *a, **k): pass
        def extract_page(self, image):
            return pp.OcrResult(markdown='Preserved OCR source', page_text='Preserved OCR source')
    monkeypatch.setattr(pp, 'OpenAICompatibleOcrClient', Ocr)
    result = pp.process_page(str(path), 1, 'auto', {'enabled': False}, {
        'source_page_no': 17, 'render_cleanup_with_llm': False,
        'figure_semantic_description_required': False,
        'vlm_ocr_enabled': False, 'ocr_config': {'glm_ocr': {'enabled': True}}}, None)
    assert result['render']['markdown'] == 'Preserved OCR source'
    assert result['semantic_status']['complete'] is False
    assert 'layout' in result['semantic_status']['missing']
