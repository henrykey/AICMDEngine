import httpx
import pytest

from src.llm.thinking_probe_client import ThinkingProbeClient, ThinkingSourceExtractor
from types import SimpleNamespace


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_context_and_probe_use_session_bearer_and_expected_fingerprint():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"provider_id": "p", "model": "m", "base_url": "https://example.com/v1", "provider_fingerprint": "v1", "apiKey": "ignored"})
        return httpx.Response(200, json={"status": "accepted", "provider_fingerprint": "v1", "probed_at": "2026-11-07T00:00:00Z", "reason_code": "accepted", "body": "ignored"})

    client = ThinkingProbeClient("https://membership.example", httpx.MockTransport(handler))
    context = await client.context("p", "user-token")
    assert context == {"provider_id": "p", "model": "m", "base_url": "https://example.com/v1", "provider_fingerprint": "v1"}
    result = await client.probe("p", "user-token", "task", {"reasoning_effort": "low"}, "v1")
    assert result["status"] == "accepted" and "body" not in result
    assert all(request.headers["authorization"] == "Bearer user-token" for request in requests)
    assert requests[0].extensions["timeout"]["read"] == 10.0
    assert requests[1].extensions["timeout"]["read"] == 70.0
    assert b'"expected_provider_fingerprint":"v1"' in requests[1].content


@pytest.mark.anyio
@pytest.mark.parametrize("status", [302, 401, 403, 404, 500])
async def test_non_success_never_becomes_accepted(status):
    client = ThinkingProbeClient("https://membership.example", httpx.MockTransport(lambda request: httpx.Response(status)))
    assert await client.context("p", "token") is None
    assert await client.probe("p", "token", "task", {"enable_thinking": True}, "v1") is None


@pytest.mark.anyio
async def test_rejects_path_injection_and_stale_fingerprint():
    client = ThinkingProbeClient("https://membership.example", httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "accepted", "provider_fingerprint": "v2", "probed_at": "now", "reason_code": "ok"})))
    assert await client.context("../admin", "token") is None
    assert await client.probe("p", "token", "task", {"enable_thinking": True}, "v1") is None


@pytest.mark.anyio
@pytest.mark.parametrize("parameters", [{}, {"model": "other"}, {"reasoning_effort": "ultra"},
    {"thinking": {"type": "enabled", "extra": 1}}, {"enable_thinking": 1},
    {"thinking": {"type": "enabled"}, "enable_thinking": True}])
async def test_invalid_candidates_are_not_sent(parameters):
    def unexpected(request):
        raise AssertionError("invalid candidate was sent")
    client = ThinkingProbeClient("https://membership.example", httpx.MockTransport(unexpected))
    assert await client.probe("p", "token", "task", parameters, "v1") is None


@pytest.mark.anyio
async def test_timeout_is_indeterminate():
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)
    client = ThinkingProbeClient("https://membership.example", httpx.MockTransport(timeout))
    assert await client.probe("p", "token", "task", {"enable_thinking": True}, "v1") is None


@pytest.mark.anyio
async def test_oversized_response_is_indeterminate():
    client = ThinkingProbeClient("https://membership.example", httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * 131073)))
    assert await client.context("p", "token") is None


@pytest.mark.anyio
async def test_extractor_sends_only_source_metadata_and_checks_fingerprint():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"provider_fingerprint": "v1", "status": "candidates", "candidates": {}})
    extractor = ThinkingSourceExtractor(ThinkingProbeClient("https://membership.example", httpx.MockTransport(handler)))
    current = {"provider_id": "p", "provider_fingerprint": "v1"}
    source = {"url": "https://docs.example/doc", "document": "document body"}
    assert await extractor.extract(SimpleNamespace(token="token"), current, source) == {}
    assert b"document body" not in requests[0].content
    assert b"source_sha256" in requests[0].content
    assert requests[0].extensions["timeout"]["read"] == 160.0
    current["provider_fingerprint"] = "v2"
    assert await extractor.extract(SimpleNamespace(token="token"), current, source) is None


@pytest.mark.anyio
async def test_multi_source_contract_sends_hashes_not_source_contents():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"provider_fingerprint": "v1", "status": "candidates", "claims": []})
    extractor = ThinkingSourceExtractor(ThinkingProbeClient("https://membership.example", httpx.MockTransport(handler)))
    sources = [{"url": "https://docs.example/doc", "sha256": "a" * 64, "document": "do not send"}]
    assert await extractor.extract_sources(SimpleNamespace(token="token"), {"provider_id": "p", "provider_fingerprint": "v1"}, sources) == []
    assert b"do not send" not in requests[0].content and b'"sources"' in requests[0].content
    assert requests[0].extensions["timeout"]["read"] == 160.0


@pytest.mark.anyio
async def test_multi_source_extractor_returns_only_allowlisted_failure_reason():
    def response(reason):
        return httpx.MockTransport(lambda request: httpx.Response(200, json={
            "provider_fingerprint": "v1", "status": "indeterminate", "reason_code": reason}))
    context = SimpleNamespace(token="token")
    current = {"provider_id": "p", "provider_fingerprint": "v1"}
    extractor = ThinkingSourceExtractor(ThinkingProbeClient("https://membership.example", response("source_timeout")))
    assert await extractor.extract_sources(context, current, []) == {"reason_code": "source_timeout"}
    extractor = ThinkingSourceExtractor(ThinkingProbeClient("https://membership.example", response("sensitive upstream error")))
    assert await extractor.extract_sources(context, current, []) == {"reason_code": "candidate_extraction_failed"}
