"""Fail-closed model capability interface until the probe service is available."""

import json
import re
from dataclasses import dataclass, field

from src.llm.thinking_official_sources import is_official_source
from src.llm.thinking_probe_client import _valid_parameters
from src.llm.thinking_discovery import discover_from_sources
from src.llm.thinking_evidence import OPTIONS

from ..mcp import BaseMCPServer, Tool, ToolResult


@dataclass(frozen=True)
class CapabilityExecutionContext:
    """Identity supplied by an authenticated entry point, never tool arguments."""
    tenant_id: str
    token: str = field(repr=False)


def _valid_capability_evidence(capabilities, source_urls):
    if not isinstance(capabilities, dict) or set(capabilities) != set(OPTIONS):
        return False
    def reference(ref):
        return (isinstance(ref, dict) and set(ref) == {"url", "quote"} and ref["url"] in source_urls
                and isinstance(ref["quote"], str) and 1 <= len(ref["quote"]) <= 5000)
    for dimension, options in OPTIONS.items():
        group = capabilities.get(dimension)
        if not isinstance(group, dict) or set(group) != options:
            return False
        for item in group.values():
            if not isinstance(item, dict) or item.get("status") not in {"unknown", "conflict", "http_accepted", "documented_unsupported", "indeterminate"}:
                return False
            if item["status"] == "unknown":
                if set(item) != {"status"}:
                    return False
                continue
            evidence = item.get("evidence")
            if set(item) != {"status", "evidence"} or not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
                return False
            for entry in evidence:
                if item["status"] == "conflict":
                    if (not isinstance(entry, dict) or set(entry) != {"support", "scope", "series", "evidence_level", "evidence", "relation_evidence"}
                            or entry["support"] not in {"supported", "unsupported"} or entry["scope"] not in {"exact", "series"}
                            or entry["evidence_level"] != ("model_explicit" if entry["scope"] == "exact" else "family_inference")
                            or not reference(entry["evidence"])
                            or (entry["scope"] == "exact" and (entry["series"] is not None or entry["relation_evidence"] is not None))
                            or (entry["scope"] == "series" and (not isinstance(entry["series"], str) or not entry["series"]
                                or not reference(entry["relation_evidence"])))):
                        return False
                elif (not isinstance(entry, dict) or set(entry) != {"scope", "series", "evidence_level", "evidence", "relation_evidence"}
                        or entry["scope"] not in {"exact", "series"} or not reference(entry["evidence"])
                        or entry["evidence_level"] != ("model_explicit" if entry["scope"] == "exact" else "family_inference")
                        or (entry["scope"] == "exact" and (entry["series"] is not None or entry["relation_evidence"] is not None))
                        or (entry["scope"] == "series" and (not isinstance(entry["series"], str) or not entry["series"]
                            or not reference(entry["relation_evidence"])))):
                    return False
    return True


def _mode_matches_parameters(mode, parameters):
    if mode in {"low", "high", "max"}:
        return (parameters.get("reasoning_effort") == mode
                and ("thinking" not in parameters or parameters["thinking"] == {"type": "enabled"})
                and ("enable_thinking" not in parameters or parameters["enable_thinking"] is True))
    if mode in {"enabled", "disabled"}:
        return parameters in ({"thinking": {"type": mode}}, {"enable_thinking": mode == "enabled"})
    return False


async def get_thinking_capabilities(provider_id: str, context: CapabilityExecutionContext = None,
                                    client=None, store=None, expected_model=None, expected_base_url=None) -> dict:
    """Return the safe policy while tenant-scoped discovery is unavailable."""
    if not isinstance(provider_id, str) or not provider_id.strip() or len(provider_id) > 256:
        raise ValueError("A valid provider_id is required")
    fallback = {
        "provider_id": provider_id,
        "status": "indeterminate",
        "reason_code": "tenant_probe_unavailable" if context else "authenticated_context_missing",
        "modes": ["default"],
        "parameters": {},
    }
    if context is None or client is None or store is None:
        return fallback
    try:
        current = await client.context(provider_id, context.token)
        if not current:
            return fallback
        if ((expected_model is not None and current["model"] != expected_model)
                or (expected_base_url is not None and current["base_url"] != expected_base_url)):
            fallback["reason_code"] = "runtime_provider_mismatch"
            return fallback
        record = await store.read(context.tenant_id, provider_id, current["provider_fingerprint"])
        if not record:
            fallback["reason_code"] = "capability_missing_or_stale"
            return fallback
        if record.get("schema_version") == 2:
            sources = record.get("sources")
            capabilities = record.get("capabilities")
            parameters = record.get("parameters")
            probes = record.get("probes")
            modes = record.get("modes")
            repairs = record.get("evidence_repairs", [])
            mapping = {"enabled": ("thinking", "enabled"), "disabled": ("thinking", "disabled"),
                       "low": ("reasoning_effort", "low"), "high": ("reasoning_effort", "high"),
                       "max": ("reasoning_effort", "max")}
            if (record.get("model") != current["model"] or record.get("base_url") != current["base_url"]
                    or not isinstance(sources, list) or not sources or len(sources) > 5
                    or any(not isinstance(s, dict) or set(s) != {"url", "sha256"}
                           or not is_official_source(current["base_url"], s["url"])
                           or not isinstance(s["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", s["sha256"]) for s in sources)
                    or not isinstance(repairs, list) or len(repairs) > 21
                    or any(not isinstance(item, dict) or set(item) != {"url", "field", "method", "original_sha256", "restored_sha256"}
                           or item["url"] not in {source["url"] for source in sources}
                           or item["field"] not in {"evidence", "relation_evidence"} or item["method"] not in {"unique_ellipsis", "unique_model_context"}
                           or any(not isinstance(item[key], str) or not re.fullmatch(r"[0-9a-f]{64}", item[key])
                                  for key in ("original_sha256", "restored_sha256")) for item in repairs)
                    or not isinstance(parameters, dict) or not isinstance(probes, dict)
                    or not isinstance(modes, list) or not modes or modes[0] != "default"
                    or len(modes) != len(set(modes)) or set(modes[1:]) != set(parameters)
                    or set(probes) != set(parameters) or not isinstance(capabilities, dict)
                    or set(parameters) - set(mapping)
                    or record.get("status") != ("http_accepted" if parameters else "indeterminate")
                    or any(not _valid_parameters(value) or not _mode_matches_parameters(mode, value)
                           for mode, value in parameters.items())
                    or not _valid_capability_evidence(capabilities, {s["url"] for s in sources})
                    or any(not isinstance(probe, dict) or probe.get("status") != "accepted"
                           or not isinstance(probe.get("probed_at"), str) or not probe["probed_at"] for probe in probes.values())
                    or any(not isinstance(capabilities.get(dim), dict)
                           or not isinstance(capabilities[dim].get(option), dict)
                           or capabilities[dim][option].get("status") != "http_accepted"
                           for mode in parameters for dim, option in [mapping[mode]])
                    or any(capabilities[dim][option].get("status") == "http_accepted" and mode not in parameters
                           for mode, (dim, option) in mapping.items())):
                fallback["reason_code"] = "invalid_capability_record"
                return fallback
            return {"provider_id": provider_id, "status": record["status"],
                "reason_code": "http_2xx" if parameters else "no_accepted_candidate", "modes": modes,
                "parameters": parameters, "sources": sources, "capabilities": capabilities,
                "evidence_repairs": repairs,
                "diagnostics": {key: value for key, value in record.get("diagnostics", {}).items()
                    if key in {"claim_shape", "claim_category", "evidence_shape", "evidence_not_exact", "family_relation_shape",
                        "family_relation_unverified", "exact_relation_unexpected", "evidence_model_missing", "evidence_dimension_missing",
                        "evidence_option_missing", "support_context_ambiguous",
                        "parameter_shape", "parameter_option_mismatch", "parameter_evidence_missing", "unsupported_has_parameters"}
                    and isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 20},
                "expires_at": record["expires_at"].isoformat()}
        # Old records lack separate switch/effort and source-level provenance.
        fallback["reason_code"] = "legacy_capability_record"
        return fallback
    except Exception:
        return fallback


async def resolve_thinking_parameters(provider_id, requested_mode, runtime_model, runtime_base_url,
                                      context, client, store):
    """Resolve a request policy only when its runtime target matches the tenant provider."""
    default = {"mode": "default", "parameters": {}, "reason_code": "unsupported_or_unavailable"}
    if (not isinstance(requested_mode, str) or requested_mode not in {"low", "high", "max", "enabled", "disabled"} or not isinstance(runtime_model, str)
            or not runtime_model or not isinstance(runtime_base_url, str) or not runtime_base_url):
        return default
    capability = await get_thinking_capabilities(provider_id, context, client, store,
                                                  expected_model=runtime_model, expected_base_url=runtime_base_url)
    if capability["status"] != "http_accepted" or requested_mode not in capability["modes"]:
        default["reason_code"] = capability.get("reason_code", default["reason_code"])
        return default
    return {"mode": requested_mode, "parameters": capability["parameters"][requested_mode], "reason_code": "http_2xx"}


class ModelCapabilitiesMCPServer(BaseMCPServer):
    def __init__(self, client=None, store=None, extractor=None, runtime=None):
        super().__init__("model-capabilities", "0.1")
        self.client = client
        self.store = store
        self.extractor = extractor
        self.runtime = runtime
        self.is_builtin = True
        self.register_tool(Tool(
            name="get_thinking_capabilities",
            description="Read thinking capabilities; returns default while discovery is unavailable.",
            input_schema={
                "type": "object",
                "properties": {"provider_id": {"type": "string", "minLength": 1, "maxLength": 256}},
                "required": ["provider_id"],
            },
            handler=self.get_thinking_capabilities,
        ))
        self.register_tool(Tool(
            name="discover_thinking_capabilities",
            description="Discover and probe documented thinking parameters; defaults when discovery is unavailable.",
            input_schema={"type": "object", "properties": {
                "provider_id": {"type": "string", "minLength": 1, "maxLength": 256}},
                "required": ["provider_id"]},
            handler=self.discover_thinking_capabilities,
        ))
        self.register_tool(Tool(
            name="discover_runtime_thinking_capabilities",
            description="Discover thinking for the provider currently bound to an MCP service.",
            input_schema={"type": "object", "properties": {"server_name": {"type": "string"}},
                          "required": ["server_name"]},
            handler=self.discover_runtime_thinking_capabilities,
        ))
        self.register_tool(Tool(
            name="get_runtime_thinking_capabilities",
            description="Read currently valid thinking capability for an MCP service's bound provider.",
            input_schema={"type": "object", "properties": {"server_name": {"type": "string"}},
                          "required": ["server_name"]},
            handler=self.discover_runtime_thinking_capabilities,
        ))

    async def get_thinking_capabilities(self, provider_id: str) -> ToolResult:
        result = await get_thinking_capabilities(provider_id)
        return ToolResult.success(json.dumps(result), data=result)

    async def discover_thinking_capabilities(self, provider_id: str) -> ToolResult:
        result = {"status": "indeterminate", "reason_code": "authenticated_context_missing", "modes": ["default"]}
        return ToolResult.success(json.dumps(result), data=result)

    async def discover_runtime_thinking_capabilities(self, server_name: str) -> ToolResult:
        return ToolResult.success(json.dumps({"status": "indeterminate", "reason_code": "authenticated_context_missing", "modes": ["default"]}))

    async def execute_with_context(self, tool_name: str, context, **kwargs) -> ToolResult:
        if tool_name not in {"get_thinking_capabilities", "discover_thinking_capabilities", "discover_runtime_thinking_capabilities", "get_runtime_thinking_capabilities"}:
            return await self.execute_tool(tool_name, **kwargs)
        if not isinstance(context, CapabilityExecutionContext):
            context = None
        try:
            if tool_name in {"discover_runtime_thinking_capabilities", "get_runtime_thinking_capabilities"}:
                operation = self.runtime.discover if tool_name == "discover_runtime_thinking_capabilities" and self.runtime else getattr(self.runtime, "read", None)
                result = await operation(kwargs.get("server_name"), context) if operation else {
                    "status": "indeterminate", "reason_code": "runtime_service_unavailable", "modes": ["default"]}
            elif tool_name == "discover_thinking_capabilities":
                from src.llm.runtime_thinking import fetch_runtime_sources
                result = await discover_from_sources(kwargs.get("provider_id"), context, self.client, self.store, self.extractor, fetch_runtime_sources)
            else:
                result = await get_thinking_capabilities(kwargs.get("provider_id"), context, self.client, self.store)
            return ToolResult.success(json.dumps(result), data=result)
        except ValueError:
            return ToolResult.error("Invalid provider_id", error_code="INVALID_PARAMS")
