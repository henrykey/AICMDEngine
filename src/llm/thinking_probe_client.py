"""Bounded client for Membership's tenant-authorized thinking probe contract."""

from urllib.parse import quote
from hashlib import sha256
import json

import httpx

EXTRACTION_FAILURE_REASONS = {"model_output_invalid", "model_output_empty", "model_output_truncated", "model_request_failed", "model_timeout", "model_connection_failed",
    "model_auth_failed", "model_rate_limited", "model_request_rejected", "model_upstream_failed", "duplicate_source", "source_timeout",
    "source_http_error", "source_too_large", "source_hash_mismatch", "invalid_model_json", "provider_changed",
    "provider_changed_or_no_candidates", "source_fetch_failed", "model_call_failed", "model_json_failed",
    "claim_structure_invalid", "evidence_quote_invalid", "relation_quote_invalid", "series_relation_invalid",
    "exact_model_missing", "unverified_evidence"}


def _valid_parameters(parameters):
    if not isinstance(parameters, dict) or not parameters:
        return False
    if set(parameters) - {"reasoning_effort", "enable_thinking", "thinking"}:
        return False
    if "thinking" in parameters and "enable_thinking" in parameters:
        return False
    if "reasoning_effort" in parameters:
        effort = parameters["reasoning_effort"]
        if not isinstance(effort, str) or effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            return False
    if "enable_thinking" in parameters and not isinstance(parameters["enable_thinking"], bool):
        return False
    if "thinking" in parameters and parameters["thinking"] not in ({"type": "enabled"}, {"type": "disabled"}):
        return False
    return True


class ThinkingProbeClient:
    def __init__(self, membership_url: str, transport=None):
        self.base_url = membership_url.rstrip("/")
        self.transport = transport

    async def _request(self, method, provider_id, token, suffix, body=None):
        if not isinstance(provider_id, str) or not provider_id.strip() or len(provider_id) > 256:
            return None
        # Reject separators, including dot path segments; this is an identifier, not a URL.
        if provider_id in {".", ".."} or any(c in provider_id for c in "/\\%?#"):
            return None
        if not isinstance(token, str) or not token.strip():
            return None
        url = f"{self.base_url}/api/internal/llm/providers/{quote(provider_id, safe='')}/{suffix}"
        try:
            read_timeout = 160.0 if suffix == "thinking-source-extractions" else 70.0 if method == "POST" else 10.0
            timeout = httpx.Timeout(read_timeout, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                async with client.stream(method, url, headers={"Authorization": f"Bearer {token}"}, json=body) as response:
                    if response.status_code != 200:
                        return None
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 131072:
                            return None
                        chunks.append(chunk)
                    result = json.loads(b"".join(chunks))
                return result if isinstance(result, dict) else None
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            return None

    async def context(self, provider_id, token):
        result = await self._request("GET", provider_id, token, "thinking-context")
        if not result or result.get("provider_id") != provider_id:
            return None
        if not all(isinstance(result.get(k), str) and result[k].strip()
                   for k in ("model", "base_url", "provider_fingerprint")):
            return None
        return {key: result[key] for key in ("provider_id", "model", "base_url", "provider_fingerprint")}

    async def probe(self, provider_id, token, task_id, parameters, fingerprint):
        if not _valid_parameters(parameters) or not isinstance(task_id, str) or not task_id:
            return None
        if not isinstance(fingerprint, str) or not fingerprint:
            return None
        result = await self._request("POST", provider_id, token, "thinking-probes", {
            "discovery_task_id": task_id, "candidate_parameters": parameters,
            "expected_provider_fingerprint": fingerprint,
        })
        if not result or result.get("status") not in {"accepted", "rejected", "indeterminate"}:
            return None
        if result.get("provider_fingerprint") != fingerprint:
            return None
        if not all(isinstance(result.get(k), str) and result[k] for k in ("probed_at", "reason_code")):
            return None
        return {key: result[key] for key in ("status", "provider_fingerprint", "probed_at", "reason_code")}


class ThinkingSourceExtractor:
    def __init__(self, client):
        self.client = client

    async def extract(self, context, current, source):
        result = await self.client._request("POST", current["provider_id"], context.token,
            "thinking-source-extractions", {
                "expected_provider_fingerprint": current["provider_fingerprint"],
                "source_url": source["url"],
                "source_sha256": sha256(source["document"].encode("utf-8")).hexdigest(),
            })
        if (not result or result.get("provider_fingerprint") != current["provider_fingerprint"]
                or result.get("status") != "candidates" or not isinstance(result.get("candidates"), dict)):
            return None
        return result["candidates"]

    async def extract_sources(self, context, current, sources):
        result = await self.client._request("POST", current["provider_id"], context.token,
            "thinking-source-extractions", {"expected_provider_fingerprint": current["provider_fingerprint"],
                "sources": [{"url": source["url"], "sha256": source["sha256"]} for source in sources]})
        if not result or result.get("provider_fingerprint") != current["provider_fingerprint"]:
            return None
        if result.get("status") == "indeterminate":
            reason = result.get("reason_code")
            return {"reason_code": reason if isinstance(reason, str) and reason in EXTRACTION_FAILURE_REASONS else "candidate_extraction_failed"}
        if result.get("status") != "candidates" or not isinstance(result.get("claims"), list):
            return None
        return result["claims"]
