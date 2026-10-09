"""Automatic calculations reuse scoped OCR without another image-model call."""
import pytest











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
