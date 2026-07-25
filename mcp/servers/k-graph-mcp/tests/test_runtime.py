from types import SimpleNamespace

from k_graph_mcp.extraction import PageFactExtractor
from k_graph_mcp.lifecycle import VolatileModelConfigRegistry
from k_graph_mcp import runtime
from k_graph_mcp.runtime import RuntimeConfig
from k_graph_mcp import __main__ as entrypoint


def test_runtime_config_reads_explicit_http_bind(monkeypatch) -> None:
  monkeypatch.setenv(
    "K_GRAPH_MCP_MONGODB_URI",
    "mongodb://mongo:27017/docintel",
  )
  monkeypatch.setenv("MEMBERSHIP_API_URL", "http://membership-api:8080")
  monkeypatch.setenv("OPENAI_API_KEY", "test-key")
  monkeypatch.setenv("K_GRAPH_MCP_LLM_MODEL", "test-model")
  monkeypatch.setenv("MCP_HOST", "0.0.0.0")
  monkeypatch.setenv("MCP_PORT", "9013")
  monkeypatch.setenv("OPENAI_BASE_URL", "")

  config = RuntimeConfig.from_env()

  assert config.mcp_host == "0.0.0.0"
  assert config.mcp_port == 9013
  assert config.llm_base_url is None


def test_entrypoint_runs_http_and_closes_runtime(monkeypatch) -> None:
  events: list[object] = []

  class FakeMcp:
    def run(self, *, transport):
      events.append(("run", transport))

  class FakeRuntime:
    mcp = FakeMcp()

    def close(self):
      events.append("close")

  monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
  monkeypatch.setattr(
    entrypoint,
    "create_runtime_from_env",
    lambda: FakeRuntime(),
  )

  entrypoint.main()

  assert events == [("run", "streamable-http"), "close"]


def test_runtime_provider_config_overrides_static_extractor(monkeypatch) -> None:
  created_clients = []

  class FakeOpenAI:
    def __init__(self, **kwargs):
      created_clients.append(kwargs)

  registry = VolatileModelConfigRegistry()
  registry.put("build-1", {
    "provider": "Qwen",
    "model": "qwen-plus",
    "base_url": "https://dashscope.example/v1",
    "api_key": "runtime-secret",
    "timeout_sec": 45,
  })
  fallback = PageFactExtractor(client=object())
  monkeypatch.setattr(runtime, "OpenAI", FakeOpenAI)

  extractor = runtime.BasinGraphRuntime._extractor_for(
    SimpleNamespace(build_id="build-1"),
    model_configs=registry,
    fallback=fallback,
  )

  assert extractor is not fallback
  assert created_clients == [{
    "api_key": "runtime-secret",
    "base_url": "https://dashscope.example/v1",
    "timeout": 45,
  }]
