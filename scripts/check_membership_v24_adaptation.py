#!/usr/bin/env python3
"""
Semi-automated adaptation checker for Membership v2.4 changes.

Checks:
1. Primary OpenAPI document exists
2. Key Membership v2.4 paths are present
3. Membership MCP tool registrations exist for expected task tools
4. Semantic metadata coverage for tools
5. Optional local verification commands
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

import yaml


ROOT = Path(__file__).resolve().parents[1]
PRIMARY_OPENAPI = ROOT / "docs" / "membership_docs" / "membership_v2.4_openapi.yaml"
LEGACY_OPENAPI = ROOT / "docs" / "membership_v2.4_openapi.yaml"
MEMBERSHIP_MCP = ROOT / "src" / "mcp_servers" / "membership_mcp.py"
MODULAR_OPENAPI = ROOT / "docs" / "membership_docs" / "openapi" / "v2.4-modular" / "openapi.yaml"
MODULAR_LLM_PATHS = ROOT / "docs" / "membership_docs" / "openapi" / "v2.4-modular" / "paths" / "llm.yaml"
MODULAR_USAGE_CONFIG_PATHS = ROOT / "docs" / "membership_docs" / "openapi" / "v2.4-modular" / "paths" / "usage-configs.yaml"


EXPECTED_ENDPOINT_TOOL_MAP: Dict[str, Dict[str, List[str]]] = {
    "/v2/members/{id}/roles": {
        "variants": ["/v2/members/{id}/roles"],
        "tools": ["get_member_roles"],
    },
    "llm_providers": {
        "variants": ["/v2/llm/providers"],
        "tools": ["list_llm_providers", "create_llm_provider"],
    },
    "llm_provider_by_name": {
        "variants": ["/v2/llm/providers/{name}"],
        "tools": ["get_llm_provider", "update_llm_provider", "delete_llm_provider"],
    },
    "llm_provider_enabled": {
        "variants": ["/v2/llm/providers/{name}/enabled"],
        "tools": ["set_llm_provider_enabled"],
    },
    "llm_provider_active": {
        "variants": ["/v2/llm/providers/{name}/active"],
        "tools": ["set_active_llm_provider"],
    },
    "llm_usage_configs": {
        "variants": ["/v2/llm/usage-configs"],
        "tools": ["list_llm_usage_configs"],
    },
    "llm_usage_config_by_purpose": {
        "variants": ["/v2/llm/usage-configs/{purpose}"],
        "tools": ["upsert_llm_usage_config", "delete_llm_usage_config"],
    },
    "llm_usage_config_resolved": {
        "variants": ["/v2/llm/usage-configs/{purpose}/resolved"],
        "tools": ["resolve_llm_usage_config"],
    },
}


@dataclass
class ToolInfo:
    name: str
    has_semantic_description: bool
    has_use_cases: bool
    has_examples: bool
    has_output_description: bool


def load_openapi_paths(path: Path) -> Set[str]:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    paths = spec.get("paths", {}) if isinstance(spec, dict) else {}
    return set(paths.keys())


def load_paths_from_files(paths: List[Path]) -> Set[str]:
    combined: Set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(spec, dict):
            combined.update(spec.keys())
    return combined


def parse_membership_tools(path: Path) -> Dict[str, ToolInfo]:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    tools: Dict[str, ToolInfo] = {}

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id == "Tool":
                kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                name_node = kwargs.get("name")
                if isinstance(name_node, ast.Constant) and isinstance(name_node.value, str):
                    name = name_node.value
                    tools[name] = ToolInfo(
                        name=name,
                        has_semantic_description="semantic_description" in kwargs,
                        has_use_cases="use_cases" in kwargs,
                        has_examples="natural_language_examples" in kwargs,
                        has_output_description="output_description" in kwargs,
                    )
            self.generic_visit(node)

    Visitor().visit(module)
    return tools


def run_command(cmd: List[str], cwd: Path) -> Tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout


def print_section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Membership v2.4 adaptation status.")
    parser.add_argument("--with-build", action="store_true", help="Also run frontend build (plan2/npm run build).")
    args = parser.parse_args()

    failures: List[str] = []
    warnings: List[str] = []

    print_section("OpenAPI Sources")
    if not PRIMARY_OPENAPI.exists():
        failures.append(f"Missing primary OpenAPI: {PRIMARY_OPENAPI}")
    else:
        print(f"Primary: OK - {PRIMARY_OPENAPI}")

    if LEGACY_OPENAPI.exists():
        warnings.append(
            f"Legacy OpenAPI copy still exists: {LEGACY_OPENAPI}. Keep it synchronized or explicitly deprecate it."
        )
        print(f"Legacy copy present: {LEGACY_OPENAPI}")
    else:
        print("Legacy copy: not present")

    if failures:
        for item in failures:
            print(f"FAIL: {item}")
        return 1

    openapi_paths = load_openapi_paths(PRIMARY_OPENAPI)
    modular_paths = load_openapi_paths(MODULAR_OPENAPI) if MODULAR_OPENAPI.exists() else set()
    supplemental_paths = load_paths_from_files([MODULAR_LLM_PATHS, MODULAR_USAGE_CONFIG_PATHS])
    all_known_paths = set(openapi_paths) | set(modular_paths) | set(supplemental_paths)
    print_section("Endpoint Coverage")
    for logical_name, spec in EXPECTED_ENDPOINT_TOOL_MAP.items():
        variants = spec["variants"]
        matched = [endpoint for endpoint in variants if endpoint in all_known_paths]
        if not matched:
            failures.append(f"OpenAPI missing endpoint variants: {variants}")
            print(f"FAIL: {logical_name} -> none of {variants}")
        else:
            for endpoint in matched:
                origin = []
                if endpoint in openapi_paths:
                    origin.append("primary")
                if endpoint in modular_paths:
                    origin.append("modular-openapi")
                if endpoint in supplemental_paths:
                    origin.append("modular-path")
                print(f"OK: {endpoint} ({', '.join(origin)})")
                if endpoint not in openapi_paths:
                    warnings.append(
                        f"Endpoint {endpoint} is not present in primary OpenAPI, only in modular/supplemental docs. Consider bundling/synchronizing the primary spec."
                    )
            if len(matched) != len(variants) and len(variants) > 1:
                warnings.append(
                    f"Endpoint variants diverge for {logical_name}. Present: {matched}; missing: {[v for v in variants if v not in matched]}"
                )

    tools = parse_membership_tools(MEMBERSHIP_MCP)
    print_section("Tool Coverage")
    for logical_name, spec in EXPECTED_ENDPOINT_TOOL_MAP.items():
        expected_tools = spec["tools"]
        for tool_name in expected_tools:
            if tool_name not in tools:
                failures.append(f"Missing MCP tool for {logical_name}: {tool_name}")
                print(f"FAIL: {tool_name} (for {logical_name})")
            else:
                print(f"OK: {tool_name}")

    print_section("Semantic Metadata")
    missing_semantics = []
    for name, info in sorted(tools.items()):
        if not (info.has_semantic_description and info.has_use_cases and info.has_examples and info.has_output_description):
            missing_semantics.append(name)
    if missing_semantics:
        print(f"Tools lacking full semantic metadata: {len(missing_semantics)}")
        for name in missing_semantics:
            print(f"- {name}")
    else:
        print("All tools include semantic metadata.")

    print_section("Compile Checks")
    code, output = run_command(
        ["python", "-m", "py_compile", "src/mcp_servers/membership_mcp.py", "src/services/direct_mcp_executor.py", "src/services/command_retriever.py"],
        ROOT,
    )
    if code == 0:
        print("OK: py_compile")
    else:
        failures.append("py_compile failed")
        print(output.strip())

    if args.with_build:
        print_section("Frontend Build")
        code, output = run_command(["npm", "run", "build"], ROOT / "plan2")
        if code == 0:
            print("OK: plan2 build")
        else:
            failures.append("plan2 build failed")
            print(output.strip())

    print_section("Summary")
    print(f"Tool count discovered: {len(tools)}")
    print(f"Primary OpenAPI path count: {len(openapi_paths)}")
    print(f"Combined known path count: {len(all_known_paths)}")
    print(f"Warnings: {len(warnings)}")
    for item in warnings:
        print(f"WARN: {item}")
    print(f"Failures: {len(failures)}")
    for item in failures:
        print(f"FAIL: {item}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
