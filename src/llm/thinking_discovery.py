"""Bounded discovery orchestration; extraction is an injected tenant-scoped service."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from .thinking_official_sources import fetch_official_source
from .thinking_probe_client import EXTRACTION_FAILURE_REASONS, _valid_parameters
from .thinking_evidence import OPTIONS, restore_claim_quotes, validate_claims


async def discover_from_sources(provider_id, context, client, store, extractor, source_fetcher):
    """Discover independent switch/effort claims, retaining evidence per source."""
    fallback = {"status": "indeterminate", "reason_code": "discovery_unavailable", "modes": ["default"]}
    if context is None or not context.tenant_id or not context.token or extractor is None:
        return fallback
    try:
        current = await client.context(provider_id, context.token)
        if not current:
            return fallback
        task_id = str(uuid4())
        await store.begin(context.tenant_id, provider_id, current["provider_fingerprint"], task_id)
        sources = await source_fetcher(current["base_url"], current["model"])
        if not sources:
            return {**fallback, "reason_code": "official_source_unavailable"}
        documents = {s["url"]: s["document"] for s in sources}
        claims = await extractor.extract_sources(context, current, sources)
        if isinstance(claims, dict):
            reason = claims.get("reason_code")
            return {**fallback, "reason_code": reason if isinstance(reason, str) and reason in EXTRACTION_FAILURE_REASONS else "candidate_extraction_failed"}
        if not isinstance(claims, list) or len(claims) > 10:
            return {**fallback, "reason_code": "candidate_extraction_failed"}
        repairs = list(getattr(claims, "repairs", []))
        claims = restore_claim_quotes(claims, documents, repairs, current["model"])
        diagnostics = {}
        accepted, conflicts = validate_claims(current["model"], documents, claims, diagnostics)
        capabilities = {dimension: {option: {"status": "unknown"} for option in sorted(options)}
                        for dimension, options in OPTIONS.items()}
        parameters, probes, evidence = {}, {}, {}
        for conflict in conflicts:
            capabilities[conflict["dimension"]][conflict["option"]] = {"status": "conflict", "evidence": conflict["evidence"]}
        mode_names = {("thinking", "enabled"): "enabled", ("thinking", "disabled"): "disabled",
                      ("reasoning_effort", "low"): "low", ("reasoning_effort", "high"): "high",
                      ("reasoning_effort", "max"): "max"}
        for (dimension, option), items in accepted.items():
            item = items[0]
            provenance = [{"scope": c["scope"], "series": c["series"],
                           "evidence_level": "model_explicit" if c["scope"] == "exact" else "family_inference", "evidence": c["evidence"],
                           "relation_evidence": c["relation_evidence"]} for c in items]
            if item["support"] == "unsupported":
                capabilities[dimension][option] = {"status": "documented_unsupported", "evidence": provenance}
                continue
            response = await client.probe(provider_id, context.token, task_id, item["parameters"], current["provider_fingerprint"])
            status = "http_accepted" if response and response.get("status") == "accepted" else "indeterminate"
            capabilities[dimension][option] = {"status": status, "evidence": provenance}
            if status == "http_accepted":
                mode = mode_names[(dimension, option)]
                parameters[mode] = item["parameters"]
                probes[mode] = {key: response.get(key) for key in ("status", "probed_at", "reason_code")}
                evidence[mode] = item["evidence"]["quote"]
        latest = await client.context(provider_id, context.token)
        if not latest or latest != current:
            return {**fallback, "reason_code": "provider_changed"}
        observed_at = datetime.now(timezone.utc)
        complete = all(item["status"] in {"http_accepted", "documented_unsupported"}
                       for group in capabilities.values() for item in group.values())
        record = {"schema_version": 2, "status": "http_accepted" if parameters else "indeterminate",
            "model": current["model"], "base_url": current["base_url"],
            "sources": [{"url": s["url"], "sha256": s["sha256"]} for s in sources],
            "capabilities": capabilities, "diagnostics": diagnostics, "evidence_repairs": repairs, "modes": ["default", *parameters], "parameters": parameters,
            "probes": probes, "evidence": evidence, "observed_at": observed_at,
            "expires_at": observed_at + (timedelta(days=30) if complete else timedelta(hours=1))}
        if not await store.save(context.tenant_id, provider_id, current["provider_fingerprint"], task_id, record):
            return {**fallback, "reason_code": "discovery_superseded"}
        return {"status": record["status"], "reason_code": "http_2xx" if parameters else "no_accepted_candidate",
                "modes": record["modes"], "capabilities": capabilities, "diagnostics": diagnostics}
    except Exception:
        return fallback


def _evidence_values(value):
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in (key, *_evidence_values(item))]
    if isinstance(value, bool):
        return [str(value).lower()]
    return [str(value)]


async def discover_thinking(provider_id, context, client, store, extractor, source_fetcher=fetch_official_source):
    fallback = {"status": "indeterminate", "reason_code": "discovery_unavailable", "modes": ["default"]}
    if context is None or not context.tenant_id or not context.token or extractor is None:
        return fallback
    try:
        current = await client.context(provider_id, context.token)
        if not current:
            return fallback
        task_id = str(uuid4())
        await store.begin(context.tenant_id, provider_id, current["provider_fingerprint"], task_id)
        source = await source_fetcher(current["base_url"])
        if not source:
            fallback["reason_code"] = "official_source_unavailable"
            return fallback
        extracted = await extractor.extract(context, current, source)
        if not isinstance(extracted, dict) or not extracted or len(extracted) > 3:
            fallback["reason_code"] = "candidate_extraction_failed"
            return fallback
        candidates = {}
        evidence = {}
        for mode, item in extracted.items():
            if not isinstance(item, dict) or set(item) != {"parameters", "evidence"}:
                fallback["reason_code"] = "candidate_extraction_failed"
                return fallback
            params, excerpt = item["parameters"], item["evidence"]
            if (mode not in {"low", "high", "disabled"} or not _valid_parameters(params)
                    or not isinstance(excerpt, str) or not 1 <= len(excerpt) <= 5000
                    or excerpt not in source["document"] or current["model"].lower() not in excerpt.lower()
                    or mode.lower() not in excerpt.lower()
                    or any(negative in excerpt.lower() for negative in (
                        "not support", "does not", "unsupported", "cannot", "不支持", "不再支持", "不允许", "不适用"))
                    or any(part.lower() not in excerpt.lower() for part in _evidence_values(params))):
                fallback["reason_code"] = "candidate_extraction_failed"
                return fallback
            candidates[mode] = params
            evidence[mode] = excerpt
        probes = {}
        for mode, params in candidates.items():
            result = await client.probe(provider_id, context.token, task_id, params, current["provider_fingerprint"])
            if not result or result["status"] != "accepted":
                fallback["reason_code"] = "candidate_not_accepted"
                return fallback
            probes[mode] = {key: result.get(key) for key in ("status", "probed_at", "reason_code")}
        latest = await client.context(provider_id, context.token)
        if not latest or latest != current:
            fallback["reason_code"] = "provider_changed"
            return fallback
        observed_at = datetime.now(timezone.utc)
        record = {
            "status": "http_accepted", "model": current["model"], "base_url": current["base_url"],
            "source": source["url"], "source_sha256": sha256(source["document"].encode("utf-8")).hexdigest(),
            "modes": ["default", *candidates], "parameters": candidates, "probes": probes, "evidence": evidence,
            "observed_at": observed_at, "expires_at": observed_at + timedelta(days=30),
        }
        if not await store.save(context.tenant_id, provider_id, current["provider_fingerprint"], task_id, record):
            fallback["reason_code"] = "discovery_superseded"
            return fallback
        return {"status": "http_accepted", "reason_code": "http_2xx", "modes": record["modes"]}
    except Exception:
        return fallback
