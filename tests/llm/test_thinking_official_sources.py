import httpx
import pytest

from src.llm.thinking_official_sources import MAX_DOCUMENT_BYTES, MAX_SOURCE_PAGES, fetch_official_source, fetch_official_sources, is_official_source, normalize_source


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_normalization_preserves_non_ascii_whitespace_and_entities():
    assert normalize_source(" \t<p> A&nbsp;<b>中</b>\u00a0B </p><script>secret</script>\n") == "A&nbsp; 中 \u00a0B"


def test_repository_trust_is_limited_to_exact_official_files():
    base = "https://open.bigmodel.cn/api/paas/v4"
    assert is_official_source(base, "https://raw.githubusercontent.com/zai-org/GLM-V/main/skills/glmv-caption/scripts/glmv_caption.py")
    assert not is_official_source(base, "https://raw.githubusercontent.com/zai-org/GLM-V/main/other.py")
    assert not is_official_source(base, "https://raw.githubusercontent.com/other/GLM-V/main/skills/glmv-caption/scripts/glmv_caption.py")


@pytest.mark.anyio
async def test_fetches_only_fixed_official_document_without_credentials():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="official documentation")
    result = await fetch_official_source("https://api.deepseek.com/v1", httpx.MockTransport(handler))
    assert result["url"] == "https://api-docs.deepseek.com/guides/thinking_mode/"
    assert requests[0].url.host == "api-docs.deepseek.com"
    assert "authorization" not in requests[0].headers


@pytest.mark.anyio
@pytest.mark.parametrize("endpoint,document_host", [
    ("https://api.z.ai/api/paas/v4", "docs.z.ai"),
    ("https://open.bigmodel.cn/api/paas/v4", "docs.bigmodel.cn"),
])
async def test_zhipu_official_hosts_map_to_their_own_sites(endpoint, document_host):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="official documentation")
    assert await fetch_official_source(endpoint, httpx.MockTransport(handler))
    assert requests[0].url.host == document_host


@pytest.mark.anyio
@pytest.mark.parametrize("endpoint", ["https://unknown.example/v1", "http://api.deepseek.com/v1",
    "https://user:pass@api.deepseek.com/v1", "https://api.deepseek.com/v1?token=secret",
    "https://api.deepseek.com:444/v1", "https://open.bigmodel.cn.attacker.example/v1"])
async def test_unknown_or_unsafe_endpoint_does_not_fetch(endpoint):
    def unexpected(request):
        raise AssertionError("unexpected request")
    assert await fetch_official_source(endpoint, httpx.MockTransport(unexpected)) is None


@pytest.mark.anyio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"location": "http://internal/"}),
    httpx.Response(200, content=b"x" * (MAX_DOCUMENT_BYTES + 1), headers={"content-type": "text/plain"}),
    httpx.Response(200, content=b"x", headers={"content-type": "application/octet-stream"})])
async def test_redirect_oversize_and_wrong_content_type_are_rejected(response):
    assert await fetch_official_source("https://api.deepseek.com/v1", httpx.MockTransport(lambda request: response)) is None


@pytest.mark.anyio
async def test_index_discovery_is_bounded_and_rejects_other_hosts_and_path_traversal():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        if request.url.path.endswith("llms.txt"):
            return httpx.Response(200, text="[model](https://docs.bigmodel.cn/cn/guide/models/glm-4.6v)\n"
                "[bad](https://evil.example/glm-4.6v)\n[bad2](https://docs.bigmodel.cn/%2e%2e/private)")
        return httpx.Response(200, text="<a href='/cn/guide/capabilities/thinking-mode'>thinking</a>")
    sources = await fetch_official_sources("https://open.bigmodel.cn/api/paas/v4", "glm-4.6v", httpx.MockTransport(handler))
    assert len(sources) <= MAX_SOURCE_PAGES
    assert any("/models/glm-4.6v" in url for url in seen)
    assert all("evil.example" not in url and "%2e%2e" not in url.lower() for url in seen)
    assert all(url in {
        "https://raw.githubusercontent.com/zai-org/GLM-V/main/skills/glmv-prompt-gen/scripts/prompt_gen.py",
        "https://raw.githubusercontent.com/zai-org/GLM-V/main/skills/glmv-caption/scripts/glmv_caption.py"}
        for url in seen if "raw.githubusercontent.com" in url)


@pytest.mark.anyio
async def test_unavailable_primary_does_not_discard_other_official_sources():
    def handler(request):
        if request.url.path.endswith("/capabilities/thinking"):
            return httpx.Response(503)
        return httpx.Response(200, text="official source")
    sources = await fetch_official_sources("https://open.bigmodel.cn/api/paas/v4", "glm-4.6v-flashx", httpx.MockTransport(handler))
    assert any(item["url"] == "https://docs.bigmodel.cn/llms.txt" for item in sources)
    assert all(item["url"] != "https://docs.bigmodel.cn/cn/guide/capabilities/thinking" for item in sources)


@pytest.mark.anyio
async def test_official_markdown_links_are_accepted():
    def handler(request):
        if request.url.path.endswith("llms.txt"):
            return httpx.Response(200, text="[model](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash.md)")
        if request.url.path.endswith("glm-5.3-flash.md"):
            return httpx.Response(200, content=b"official model", headers={"content-type": "text/markdown; charset=utf-8"})
        return httpx.Response(200, text="official source")
    sources = await fetch_official_sources("https://open.bigmodel.cn/api/paas/v4", "glm-5.3-flash", httpx.MockTransport(handler))
    assert any(source["url"].endswith("glm-5.3-flash.md") for source in sources)


@pytest.mark.anyio
async def test_official_repository_is_excluded_for_unmentioned_model():
    def handler(request):
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(200, text="GLM-4.6V/GLM-4.6V-FlashX series")
        return httpx.Response(200, text="official source")
    transport = httpx.MockTransport(handler)
    sources = await fetch_official_sources("https://open.bigmodel.cn/api/paas/v4", "glm-5.3-flash", transport)
    assert all("raw.githubusercontent.com" not in item["url"] for item in sources)
    sources = await fetch_official_sources("https://open.bigmodel.cn/api/paas/v4", "glm-4.6v-flashx", transport)
    assert any("raw.githubusercontent.com" in item["url"] for item in sources)
