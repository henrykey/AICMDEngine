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
    context_window = 128000
    dual_output_max_tokens = 16384


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


def _tool_info(*properties, schema_key="inputSchema"):
    return {
        "name": "fake",
        schema_key: {
            "type": "object",
            "properties": {name: {"type": "object"} for name in properties},
        },
    }


class FakeSchemaRegistry:
    def __init__(self, schemas=None):
        self.schemas = schemas or {}
        self.kwargs = None
        self.tool_name = None

    def get_tool_info(self, mcp_name, tool_name):
        assert mcp_name == "pdf2md-enhanced"
        return self.schemas.get(tool_name)

    def get_mcp(self, name):
        assert name == "pdf2md-enhanced"
        return object()

    async def execute_command(self, mcp_name, tool_name, llm_provider=None, **kwargs):
        assert mcp_name == "pdf2md-enhanced"
        assert llm_provider is None
        self.tool_name = tool_name
        self.kwargs = kwargs
        return type("Result", (), {"content": "ok"})()


def _protocol_inject(tool_name, arguments=None, schemas=None):
    handler = MCPProtocolHandler()
    registry = FakeSchemaRegistry(schemas or {tool_name: _tool_info("vlm_config", "ocr_config")})

    return asyncio.run(
        handler._inject_external_model_configs(
            mcp_name="pdf2md-enhanced",
            tool_name=tool_name,
            arguments=arguments or {"file_path": "/tmp/page.pdf"},
            context={"mongodb": FakeMongo(), "provider_manager": FakeProviderManager(), "registry": registry},
        )
    )


def test_protocol_injects_vlm_config_for_schema_declared_new_tool():
    args = _protocol_inject("revise_page_markdown", schemas={"revise_page_markdown": _tool_info("vlm_config")})

    assert args["vlm_config"]["provider"] == "glmocr"
    assert args["vlm_config"]["api_key"] == "secret-key"
    assert args["vlm_config"]["context_window"] == 128000
    assert args["vlm_config"]["dual_output_max_tokens"] == 16384
    assert "vlm_defaults" not in args


def test_protocol_injects_vlm_defaults_for_schema_declared_defaults_tool():
    args = _protocol_inject("start_task", schemas={"start_task": _tool_info("vlm_defaults")})

    assert args["vlm_defaults"]["provider"] == "glmocr"
    assert "vlm_config" not in args


def test_protocol_does_not_inject_vlm_when_schema_has_no_vlm_field():
    args = _protocol_inject("plain_tool", schemas={"plain_tool": _tool_info("file_path")})

    assert "vlm_config" not in args
    assert "vlm_defaults" not in args
    assert "ocr_config" not in args


def test_protocol_respects_explicit_vlm_config():
    explicit = {"provider": "manual"}
    args = _protocol_inject(
        "revise_page_markdown",
        arguments={"file_path": "/tmp/page.pdf", "vlm_config": explicit},
        schemas={"revise_page_markdown": _tool_info("vlm_config")},
    )

    assert args["vlm_config"] is explicit


def test_protocol_injects_ocr_config_when_schema_declares_ocr_config():
    args = _protocol_inject("extract_page_tables", schemas={"extract_page_tables": _tool_info("ocr_config")})

    assert args["ocr_config"]["glm_ocr"]["enabled"] is True
    assert args["ocr_config"]["glm_ocr"]["provider"] == "glmocr"
    assert args["ocr_config"]["glm_ocr"]["api_key"] == "secret-key"
    assert "vlm_config" not in args


def test_protocol_injects_ocr_config_without_api_key(monkeypatch):
    monkeypatch.setattr(FakeConfigLoader, "get_api_key", lambda self, ref: None)
    args = _protocol_inject("extract_page_tables", schemas={"extract_page_tables": _tool_info("ocr_config")})

    config = args["ocr_config"]["glm_ocr"]
    assert config["enabled"] is True
    assert config["model"] == FakeProvider.model
    assert config["base_url"] == FakeProvider.base_url
    assert config["api_key"] == ""


def test_protocol_reads_input_schema_alias():
    args = _protocol_inject("revise_page_markdown", schemas={"revise_page_markdown": _tool_info("vlm_config", schema_key="input_schema")})

    assert args["vlm_config"]["provider"] == "glmocr"


def test_pdf2md_protocol_respects_explicit_ocr_config():
    explicit = {"glm_ocr": {"enabled": False, "provider": "manual"}}

    args = _protocol_inject(
        "process_task_page",
        arguments={"ocr_config": explicit},
        schemas={"process_task_page": _tool_info("vlm_config", "ocr_config")},
    )

    assert args["ocr_config"] is explicit
    assert args["vlm_config"]["provider"] == "glmocr"


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


def _rest_execute(tool_name, schemas=None, request_cls=FakeRequest):
    registry = FakeSchemaRegistry(schemas or {tool_name: _tool_info("vlm_config", "ocr_config")})

    response = asyncio.run(
        mcp_router.execute_mcp_tool(
            server_name="pdf2md-enhanced",
            tool_name=tool_name,
            request=request_cls(registry),
        )
    )
    return response, registry


def test_rest_injects_vlm_config_for_schema_declared_new_tool():
    response, registry = _rest_execute("revise_page_markdown", schemas={"revise_page_markdown": _tool_info("vlm_config")})

    assert response["result"]["content"][0]["text"] == "ok"
    assert registry.kwargs["vlm_config"]["provider"] == "glmocr"
    assert registry.kwargs["vlm_config"]["context_window"] == 128000
    assert registry.kwargs["vlm_config"]["dual_output_max_tokens"] == 16384


def test_rest_injects_vlm_defaults_for_schema_declared_defaults_tool():
    _, registry = _rest_execute("start_task", schemas={"start_task": _tool_info("vlm_defaults")})

    assert registry.kwargs["vlm_defaults"]["provider"] == "glmocr"
    assert "vlm_config" not in registry.kwargs


def test_rest_does_not_inject_vlm_when_schema_has_no_vlm_field():
    _, registry = _rest_execute("plain_tool", schemas={"plain_tool": _tool_info("file_path")})

    assert "vlm_config" not in registry.kwargs
    assert "vlm_defaults" not in registry.kwargs
    assert "ocr_config" not in registry.kwargs


class ExplicitVlmRequest(FakeRequest):
    async def json(self):
        return {"file_path": "/tmp/page.pdf", "vlm_config": {"provider": "manual"}}


def test_rest_respects_explicit_vlm_config():
    _, registry = _rest_execute(
        "revise_page_markdown",
        schemas={"revise_page_markdown": _tool_info("vlm_config")},
        request_cls=ExplicitVlmRequest,
    )

    assert registry.kwargs["vlm_config"] == {"provider": "manual"}


def test_rest_injects_ocr_config_when_schema_declares_ocr_config():
    _, registry = _rest_execute("extract_page_tables", schemas={"extract_page_tables": _tool_info("ocr_config")})

    assert registry.kwargs["ocr_config"]["glm_ocr"]["enabled"] is True
    assert registry.kwargs["ocr_config"]["glm_ocr"]["provider"] == "glmocr"
    assert "vlm_config" not in registry.kwargs


def test_rest_injects_ocr_config_without_api_key(monkeypatch):
    monkeypatch.setattr(FakeConfigLoader, "get_api_key", lambda self, ref: None)
    _, registry = _rest_execute("extract_page_tables", schemas={"extract_page_tables": _tool_info("ocr_config")})

    config = registry.kwargs["ocr_config"]["glm_ocr"]
    assert config["enabled"] is True
    assert config["model"] == FakeProvider.model
    assert config["base_url"] == FakeProvider.base_url
    assert config["api_key"] == ""


def test_protocol_and_rest_paths_inject_consistently_for_combined_schema():
    schemas = {"extract_page_structured": _tool_info("vlm_config", "ocr_config")}
    protocol_args = _protocol_inject("extract_page_structured", schemas=schemas)
    _, registry = _rest_execute("extract_page_structured", schemas=schemas)

    assert protocol_args["vlm_config"]["provider"] == registry.kwargs["vlm_config"]["provider"] == "glmocr"
    assert protocol_args["ocr_config"]["glm_ocr"]["provider"] == registry.kwargs["ocr_config"]["glm_ocr"]["provider"] == "glmocr"
