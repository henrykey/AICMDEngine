"""Automatic calculations reuse scoped OCR without another image-model call."""
import fitz
import pytest

from tests.test_pdf2md_calculation_sheet import cs, framed_proposal


@pytest.mark.parametrize('persistence_failure', [False, True])
def test_automatic_ocr_is_saved_before_text_semantics(persistence_failure):
    events = []
    source = '# Calculation\n\n$Q=a+b$\n\nApply only when $a>0$.'
    item = {'table_kind': 'calculation_sheet', 'table_kind_source': 'automatic'}
    class VLM:
        table_analysis_max_model_calls = 2
        def extract_calculation_sheet(self, image, target):
            assert image is None
            assert events == ['save']
            assert 'Q=a+b' in target['source_text']
            events.append('semantic')
            return framed_proposal(target)
    def save(ref, selected, content):
        events.append('save')
        assert content == source
        assert selected['calculation_source']['origin'] == 'existing_ocr'
        assert 'image_sha256' not in selected['calculation_source']
        if persistence_failure:
            raise OSError('synthetic failure')
        return {'artifact_id': 'saved-ocr'}
    cs.complete_calculation_batch(VLM(), 'unused', [(item, source, 'tables:0')], 1, source_store=save)
    assert events == ['save']
    if persistence_failure:
        assert item['calculation_source']['reason'] == 'calculation_source_persistence_failed'
    else:
        assert item['calculation_source']['pipeline']['semantic']['status'] == 'not_requested'
        assert 'calculation_sheet' not in item


@pytest.mark.parametrize('content,budget,reason', [('', 2, 'calculation_source_missing'),
    ('$q=x$', 0, None)])
def test_empty_source_or_budget_never_triggers_image_fallback(content, budget, reason):
    class VLM:
        table_analysis_max_model_calls = budget
        def extract_calculation_sheet(self, *args):
            pytest.fail('No model call allowed')
    item = {'table_kind': 'calculation_sheet'}
    assert cs.complete_calculation_batch(VLM(), 'unused', [(item, content, 'tables:0')], 0) == 0
    assert item['calculation_source'].get('reason') == reason
    assert 'calculation_sheet' not in item


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
        [(item, '\n\n'.join(f'$q_{{{i}}}=a+{i}$' for i in range(45)), f'tables:{index}') for index, item in enumerate(items)], 1)
    assert count == 0
    assert calls == []
    assert all(item['calculation_source']['original_content'].count('$q_') == 45 for item in items)
    assert all('calculation_sheet' not in item for item in items)
    assert client.physical_request_limit is None


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
