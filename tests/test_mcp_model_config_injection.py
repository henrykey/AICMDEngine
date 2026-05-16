import asyncio
import importlib.util
import sys
from pathlib import Path

from src.mcp.protocol_handler import MCPProtocolHandler


ROOT = Path(__file__).resolve().parents[1]


def _load_mcp_router_module():
    module_name = "mcp_router_injection_test_module"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "src/routers/mcp.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mcp_router = _load_mcp_router_module()


class FakeProvider:
    name = "glmocr"
    model = "glm-4.5v"
    base_url = "https://example.test/v1"
    api_key_ref = "GLM_OCR_API_KEY"
    timeout = 120
    temperature = 0.1
    max_tokens = 4096


class FakeConfigLoader:
    def get_api_key(self, api_key_ref):
        assert api_key_ref == "GLM_OCR_API_KEY"
        return "secret-key"


class FakeProviderManager:
    config_loader = FakeConfigLoader()

    def get_provider(self, name):
        if name == "glmocr":
            return FakeProvider()
        return None


class FakeSettingsCollection:
    def find(self, query, projection):
        assert query == {}
        assert "glm_ocr_provider" in projection
        return self

    async def to_list(self, length):
        assert length == 1000
        return [{"server_name": "pdf2md-enhanced", "llm_provider": "glmocr", "glm_ocr_provider": "glmocr"}]

    async def find_one(self, query):
        assert query == {"server_name": "pdf2md-enhanced"}
        return {"server_name": "pdf2md-enhanced", "llm_provider": "glmocr", "glm_ocr_provider": "glmocr"}


class FakeMongo:
    mcp_server_settings = FakeSettingsCollection()


def test_pdf2md_protocol_injects_glm_ocr_config_for_single_page_tools():
    handler = MCPProtocolHandler()

    args = asyncio.run(
        handler._inject_external_model_configs(
            mcp_name="pdf2md-enhanced",
            tool_name="extract_page_tables",
            arguments={"file_path": "/tmp/page.pdf"},
            context={"mongodb": FakeMongo(), "provider_manager": FakeProviderManager()},
        )
    )

    assert args["vlm_config"]["provider"] == "glmocr"
    assert args["ocr_config"]["glm_ocr"]["enabled"] is True
    assert args["ocr_config"]["glm_ocr"]["provider"] == "glmocr"
    assert args["ocr_config"]["glm_ocr"]["api_key"] == "secret-key"


def test_pdf2md_protocol_respects_explicit_ocr_config():
    handler = MCPProtocolHandler()
    explicit = {"glm_ocr": {"enabled": False, "provider": "manual"}}

    args = asyncio.run(
        handler._inject_external_model_configs(
            mcp_name="pdf2md-enhanced",
            tool_name="process_task_page",
            arguments={"ocr_config": explicit},
            context={"mongodb": FakeMongo(), "provider_manager": FakeProviderManager()},
        )
    )

    assert args["ocr_config"] is explicit
    assert args["vlm_config"]["provider"] == "glmocr"


class FakeRegistry:
    def __init__(self):
        self.kwargs = None

    def get_mcp(self, name):
        assert name == "pdf2md-enhanced"
        return object()

    async def execute_command(self, mcp_name, tool_name, llm_provider=None, **kwargs):
        assert mcp_name == "pdf2md-enhanced"
        assert tool_name == "extract_page_tables"
        assert llm_provider is None
        self.kwargs = kwargs
        return type("Result", (), {"content": "ok"})()


class FakeApp:
    def __init__(self, registry):
        self.mongodb = FakeMongo()
        self.provider_manager = FakeProviderManager()
        self.mcp_registry = registry


class FakeRequest:
    def __init__(self, registry):
        self.app = FakeApp(registry)

    async def json(self):
        return {"file_path": "/tmp/page.pdf"}


def test_pdf2md_rest_injects_glm_ocr_config_for_single_page_tools():
    registry = FakeRegistry()

    response = asyncio.run(
        mcp_router.execute_mcp_tool(
            server_name="pdf2md-enhanced",
            tool_name="extract_page_tables",
            request=FakeRequest(registry),
        )
    )

    assert response["result"]["content"][0]["text"] == "ok"
    assert registry.kwargs["vlm_config"]["provider"] == "glmocr"
    assert registry.kwargs["ocr_config"]["glm_ocr"]["enabled"] is True
    assert registry.kwargs["ocr_config"]["glm_ocr"]["provider"] == "glmocr"


def test_pdf2md_protocol_injects_glm_ocr_config_for_layout_tool_without_vlm():
    handler = MCPProtocolHandler()

    args = asyncio.run(
        handler._inject_external_model_configs(
            mcp_name="pdf2md-enhanced",
            tool_name="analyze_page_layout",
            arguments={"file_path": "/tmp/page.pdf"},
            context={"mongodb": FakeMongo(), "provider_manager": FakeProviderManager()},
        )
    )

    assert "vlm_config" not in args
    assert args["ocr_config"]["glm_ocr"]["enabled"] is True
    assert args["ocr_config"]["glm_ocr"]["provider"] == "glmocr"


def test_pdf2md_protocol_injects_both_model_configs_for_enhanced_layout_tool():
    handler = MCPProtocolHandler()

    args = asyncio.run(
        handler._inject_external_model_configs(
            mcp_name="pdf2md-enhanced",
            tool_name="extract_page_layout_enhanced",
            arguments={"file_path": "/tmp/page.pdf"},
            context={"mongodb": FakeMongo(), "provider_manager": FakeProviderManager()},
        )
    )

    assert args["vlm_config"]["provider"] == "glmocr"
    assert args["ocr_config"]["glm_ocr"]["enabled"] is True
    assert args["ocr_config"]["glm_ocr"]["provider"] == "glmocr"
