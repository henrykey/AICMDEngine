from types import SimpleNamespace
import pytest
from tests.test_mcp_model_config_injection import FakeProvider, FakeProviderManager, mcp_router
from src.mcp.protocol_handler import MCPProtocolHandler
from tests.test_pdf2md_enhanced_single_page_tools import DynamicVLMClient


@pytest.mark.parametrize('transport', ['protocol', 'rest'])
@pytest.mark.parametrize('mode,expected', [('low', {'enable_thinking': True, 'reasoning_effort': 'low'}), ('default', {}), ('disabled', {'enable_thinking': False})])
def test_provider_thinking_reaches_image_and_text_requests(monkeypatch, tmp_path, transport, mode, expected):
    monkeypatch.setattr(FakeProvider, 'model', 'qwen3.8-27b')
    monkeypatch.setattr(FakeProvider, 'base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    monkeypatch.setattr(FakeProvider, 'thinking_mode', mode, raising=False)
    manager = FakeProviderManager()
    if transport == 'protocol':
        cfg = MCPProtocolHandler._build_model_config_from_provider(manager, 'glmocr', 'pdf2md-enhanced', 'VLM')
    else:
        cfg = mcp_router._build_vlm_config_from_provider(SimpleNamespace(app=SimpleNamespace(provider_manager=manager)), 'glmocr')
    assert cfg['thinking_mode'] == mode
    assert 'thinking_parameters' not in cfg
    client = DynamicVLMClient(cfg)
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='{}'), finish_reason='stop')])])
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    image = tmp_path / 'page.png'
    image.write_bytes(b'\x89PNG\r\n\x1a\nfake')
    client._call_image_prompt(str(image), 'test', 128)
    client._call_text_prompt('test', 128)
    assert len(requests) == 2
    for request in requests:
        assert request['model'] == 'qwen3.8-27b'
        assert request.get('extra_body', {}) == expected
