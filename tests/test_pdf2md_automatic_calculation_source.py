"""Automatic calculation sources must come from the selected object's pixels."""
import fitz
import pytest

from tests.test_pdf2md_calculation_sheet import cs, framed_proposal


@pytest.mark.parametrize('persistence_failure', [False, True])
def test_automatic_calculation_transcribes_object_before_saving_and_structuring(tmp_path, persistence_failure):
    page_path = tmp_path / 'page.png'
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
    image.clear_with(255)
    image.save(page_path)
    events = []
    source = '# Calculation\n\n$Q=a+b$\n\nApply only when $a>0$.'
    item = {'table_kind': 'calculation_sheet', 'table_kind_source': 'automatic',
            'layout_id': 'lower-object', 'bbox': [0, 0.5, 1, 1], 'bbox_space': 'normalized_page'}

    class VLM:
        table_analysis_max_model_calls = 4
        last_call_info = {}

        def extract_calculation_sheet(self, image_path, target):
            if image_path is not None:
                events.append('transcribe')
                crop = fitz.Pixmap(str(image_path))
                assert (crop.width, crop.height) == (200, 100)
                assert target['calculation_stage'] == 'transcription'
                assert target['object_ref'] == 'tables:1'
                return {**target, 'source_text': source, 'table_title': 'Calculation'}
            assert events == ['transcribe', 'save']
            events.append('semantic')
            assert 'Q=a+b' in target['source_text']
            assert 'WRONG_OCR' not in target['source_text']
            return framed_proposal(target)

    def save(ref, selected, content):
        events.append('save')
        assert events == ['transcribe', 'save']
        assert ref == 'tables:1' and selected is item and content == source
        assert selected['calculation_source']['origin'] == 'image_transcription'
        if persistence_failure:
            raise OSError('synthetic source storage failure')
        return {'artifact_id': 'saved-image-source'}

    cs.complete_calculation_batch(VLM(), str(page_path), [(item, '$WRONG_OCR$', 'tables:1')], 1,
                                  source_store=save)
    assert events == (['transcribe', 'save'] if persistence_failure else ['transcribe', 'save', 'semantic'])
    assert item['table_kind_source'] == 'automatic'
    assert item['calculation_source']['original_content'] == source
    if persistence_failure:
        assert item['calculation_source']['pipeline']['semantic']['reason'] == 'calculation_source_persistence_failed'
    else:
        assert item['calculation_source']['artifact']['artifact_id'] == 'saved-image-source'


@pytest.mark.parametrize('budget,bbox,expected', [
    (0, [0, 0, 1, 1], 'table_analysis_budget_exhausted'),
    (2, None, 'calculation_object_region_required'),
    (2, [0, 0, 2, 1], 'calculation_object_region_required'),
])
def test_automatic_source_never_uses_whole_page_or_saves_ocr_on_precondition_failure(budget, bbox, expected):
    class VLM:
        table_analysis_max_model_calls = budget
        def extract_calculation_sheet(self, *args):
            pytest.fail('no image request is authorized by this object scope/budget')
    item = {'table_kind': 'calculation_sheet', 'bbox': bbox, 'bbox_space': 'normalized_page'}
    calls = cs.complete_calculation_batch(VLM(), 'unused', [(item, '$q=x$', 'tables:0')], 0,
        source_store=lambda *args: pytest.fail('OCR fallback must not be saved as a new image source'))
    assert calls == 0
    assert item['calculation_source']['origin'] == 'existing_ocr'
    assert item['calculation_sheet']['coverage']['structured'] == 0
    assert {'reason': expected} in item['calculation_sheet']['unresolved']


def test_ordinary_table_does_not_enter_calculation_image_source_path():
    class VLM:
        table_analysis_max_model_calls = 4
        def extract_calculation_sheet(self, *args):
            pytest.fail('ordinary table must retain its existing flow')
    item = {'table_kind': 'data_table', 'markdown': '| Value |\n|---|\n| 3 |'}
    before = dict(item)
    assert cs.complete_calculation_batch(VLM(), 'unused', [(item, item['markdown'], 'tables:0')], 1,
        source_store=lambda *args: pytest.fail('not a calculation source')) == 0
    assert item == before


def test_default_automatic_budget_covers_each_object_and_actual_source_batches(tmp_path):
    from tests.test_pdf2md_enhanced_single_page_tools import DynamicVLMClient
    image_path = tmp_path / 'page.png'
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
    image.clear_with(255)
    image.save(image_path)
    client = DynamicVLMClient(None)
    calls = []
    def extract(path, target):
        calls.append((path is not None, target['object_ref']))
        if path is not None:
            return {**target, 'source_text': '\n\n'.join(f'$q_{{{i}}}=a+{i}$' for i in range(45))}
        return framed_proposal(target)
    client.extract_calculation_sheet = extract
    items = [{'table_kind': 'calculation_sheet', 'bbox': [0, y, 1, y + .5],
              'bbox_space': 'normalized_page'} for y in (0, .5)]
    count = cs.complete_calculation_batch(client, str(image_path),
        [(item, '$wrong$', f'tables:{index}') for index, item in enumerate(items)], 1)
    assert count == 6
    assert calls == [(True, 'tables:0'), (False, 'tables:0'), (False, 'tables:0'),
                     (True, 'tables:1'), (False, 'tables:1'), (False, 'tables:1')]
    assert all(item['calculation_sheet']['coverage']['structured'] == 45 for item in items)
    assert client.physical_request_limit == 16  # Shared classification allowance plus six bounded calls.


@pytest.mark.parametrize('config', [
    {'table_analysis_max_model_calls': 2},
    {'table_analysis_max_physical_requests': 1},
    {'_calculation_processing': 'reextract'},
])
def test_explicit_or_manual_budget_cannot_expand_with_automatic_work(config):
    from tests.test_pdf2md_enhanced_single_page_tools import DynamicVLMClient
    client = DynamicVLMClient(config)
    with client.calculation_scope():
        before = client.physical_request_limit
        client.reserve_automatic_calculation_calls(20)
        assert client.physical_request_limit == before
    assert client.automatic_calculation_budget is False


@pytest.mark.parametrize('value,expected', [(None, 0.1), (0, 0.0), (0.7, 0.7)])
def test_nullable_provider_temperature_preserves_explicit_zero(value, expected):
    from tests.test_pdf2md_enhanced_single_page_tools import DynamicVLMClient
    assert DynamicVLMClient({'temperature': value}).temperature == expected
