"""
Tests for form_mcp.suggest_form.

No model is involved: the caller (the Workflow AI assistant, later) supplies the suggested fields. Membership is replaced at the
request-sending step, so the real HTTPClient builds the real request (method, path, body, Authorization, X-Tenant-ID); the replacement
answers like Membership's POST /v2/workflows/assistant/proposals/check does (compiled forms plus issues). Whether a form is valid is
Membership's judgement: these tests only check that the tool asks it, with the caller's own identity, and reports what it says. No real
Membership or Router is used here.
"""

import json

import httpx
import pytest
from unittest.mock import patch

from src.mcp.registry import MCPRegistry
from src.mcp_servers.form_mcp import FORM_MCP
from tests.test_form_mcp_find_forms import TOKEN

LEAVE_FIELDS = [
    {"key": "reason", "kind": "textarea", "label": "Reason", "required": True},
    {"key": "start_date", "kind": "date", "label": "Start date", "required": True},
    {"key": "days", "kind": "number", "label": "Days", "required": True},
]
VISITOR_FIELDS = [
    {"key": "visitor_name", "kind": "text", "label": "Name", "required": True},
    {"key": "purpose", "kind": "choice", "label": "Purpose", "required": True, "options": ["meeting", "delivery"]},
    {"key": "visit_date", "kind": "date", "label": "Visit date"},
]
LEAVE = {"form_key": "leave_request", "form_name": "Leave request", "fields": LEAVE_FIELDS}
VISITOR = {"form_key": "visitor_registration", "form_name": "Visitor registration", "fields": VISITOR_FIELDS}
ID = {"auth_token": TOKEN, "tenant_id": 7}


def compiled(form):
    """What Membership's check returns for a proposal's form: the compiled schemas (a stand-in for its real compiler, for these tests)."""
    props, required, ui = {}, [], {}
    for f in form["fields"]:
        kind = f.get("kind")
        spec = {"type": {"number": "number", "boolean": "boolean"}.get(kind, "string"), "title": f.get("label")}
        if kind == "date":
            spec["format"] = "date"
        if kind == "choice":
            spec["enum"] = f.get("options", [])
        props[f["key"]] = spec
        if f.get("required"):
            required.append(f["key"])
        if kind == "textarea":
            ui[f["key"]] = {"widget": "textarea"}
    return {"formKey": form.get("formKey"), "formName": form.get("formName"),
            "formSchema": {"type": "object", "properties": props, "required": required}, "uiSchema": {"fields": ui}}


class FakeCheck:
    """Stands in for Membership's proposals/check; `issues` are what its validators would say."""

    def __init__(self, issues=None, status=200, body=None):
        self.issues, self.status, self.body, self.requests = issues or [], status, body, []

    async def __call__(self, method, url, headers, request_params, timeout):
        self.requests.append({"method": method, "url": str(url), "headers": dict(headers), "json": request_params.get("json")})
        request = httpx.Request(method, url)
        if self.status >= 400:
            return httpx.Response(self.status, json={"message": "no"}, request=request)
        if self.body is not None:
            return httpx.Response(200, json=self.body, request=request)
        if not request_params["json"]["proposal"]["forms"]:  # the permission probe: an empty proposal checks out
            return httpx.Response(200, json={"forms": [], "issues": [], "saveable": True}, request=request)
        form = request_params["json"]["proposal"]["forms"][0]
        return httpx.Response(200, json={"forms": [compiled(form)], "issues": self.issues, "saveable": not self.issues}, request=request)


def server():
    return FORM_MCP(membership_base_url="http://membership.test")


async def suggest(mcp, fake, **kwargs):
    with patch("src.services.http_client.HTTPClient._send_request", new=fake):
        return await mcp.execute_tool("suggest_form", **kwargs)


def out(result):
    return json.loads(result.content)


# ---------------------------------------------------------------- discovery

def test_the_tool_is_discoverable_takes_fields_and_has_no_model_parameter():
    registry = MCPRegistry()
    registry.register_mcp(server())
    info = registry.get_tool_info("form_mcp", "suggest_form")
    props = info["input_schema"]["properties"]
    assert {"form_key", "form_name", "fields", "auth_token", "tenant_id"} <= set(props)
    assert info["input_schema"]["required"] == ["form_key", "fields"]
    assert not {"model", "llm", "provider", "prompt", "requirement"} & set(props)
    item = props["fields"]["items"]
    assert item["additionalProperties"] is False and set(item["properties"]) == set(FORM_MCP.SUPPORTED_FIELD_PROPERTIES)
    assert sorted(t["name"] for t in registry.get_mcp_info("form_mcp")["tools"]) == ["find_forms", "suggest_form"]


def test_the_server_has_no_model_seam():
    import inspect
    assert list(inspect.signature(FORM_MCP.__init__).parameters) == ["self", "membership_base_url"]


# ---------------------------------------------------------------- valid suggestions, and not one template

@pytest.mark.asyncio
async def test_leave_fields_become_a_form_checked_by_membership_and_returned_for_viewing():
    result = await suggest(server(), FakeCheck(), **LEAVE, **ID)
    assert not result.is_error
    o = out(result)
    assert o["valid"] is True and o["saved"] is False and o["issues"] == []
    assert (o["form"]["formKey"], o["form"]["formName"]) == ("leave_request", "Leave request")
    props = o["form"]["formSchema"]["properties"]
    assert props["start_date"]["format"] == "date" and props["days"]["type"] == "number"
    assert o["form"]["formSchema"]["required"] == ["reason", "start_date", "days"]


@pytest.mark.asyncio
async def test_different_fields_give_a_different_form_so_it_is_not_a_template():
    leave = out(await suggest(server(), FakeCheck(), **LEAVE, **ID))
    visitor = out(await suggest(server(), FakeCheck(), **VISITOR, **ID))
    assert set(leave["form"]["formSchema"]["properties"]) == {"reason", "start_date", "days"}
    assert set(visitor["form"]["formSchema"]["properties"]) == {"visitor_name", "purpose", "visit_date"}
    assert visitor["form"]["formSchema"]["properties"]["purpose"]["enum"] == ["meeting", "delivery"]


@pytest.mark.asyncio
async def test_the_permission_probe_then_the_check_with_the_callers_identity_and_nothing_else():
    fake = FakeCheck()
    await suggest(server(), fake, **LEAVE, **ID)
    assert len(fake.requests) == 2  # the permission probe, then the check of the form; nothing is written
    assert all(r["method"] == "POST" and r["url"].endswith("/v2/workflows/assistant/proposals/check") for r in fake.requests)
    assert all(r["headers"]["Authorization"] == f"Bearer {TOKEN}" and r["headers"]["X-Tenant-ID"] == "7" for r in fake.requests)
    assert fake.requests[0]["json"]["proposal"]["forms"] == []
    proposal = fake.requests[1]["json"]["proposal"]
    assert [f["key"] for f in proposal["forms"][0]["fields"]] == ["reason", "start_date", "days"]
    assert proposal["steps"] == [{"name": "Starter", "formKey": "leave_request", "assignments": [{"kind": "INITIATOR"}]}]


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"maxLength": 50}, {"minimum": 0}, {"pattern": "^a"}, {"default": "x"}, {"widget": "evil"}, {"readOnly": True}, {"description": "hint"}])
async def test_a_field_property_the_tool_does_not_support_is_rejected_not_silently_dropped(extra):
    fields = [{"key": "reason", "kind": "text", "label": "Reason", "required": True, **extra}]
    fake = FakeCheck()
    result = await suggest(server(), fake, form_key="f", fields=fields, **ID)
    assert result.is_error and result.error_code == "UNSUPPORTED_FIELD_PROPERTY"
    name = next(iter(extra))
    assert f"'{name}'" in result.content and "'reason'" in result.content  # says which property on which field
    assert not fake.requests  # nothing was sent on, so nothing can be reported valid without it


@pytest.mark.asyncio
async def test_every_unsupported_property_is_named_and_the_supported_ones_alone_are_fine():
    fields = [{"key": "a", "kind": "text", "label": "A", "maxLength": 5}, {"key": "b", "kind": "number", "label": "B", "minimum": 0, "step": 1}]
    result = await suggest(server(), FakeCheck(), form_key="f", fields=fields, **ID)
    assert result.is_error and result.error_code == "UNSUPPORTED_FIELD_PROPERTY"
    for text in ("'maxLength'", "'minimum'", "'step'", "'a'", "'b'"):
        assert text in result.content
    ok = await suggest(server(), FakeCheck(), form_key="f", fields=[
        {"key": "a", "kind": "text", "label": "A", "required": True}, {"key": "c", "kind": "choice", "options": ["x"]}], **ID)
    assert not ok.is_error and out(ok)["valid"] is True


@pytest.mark.asyncio
async def test_the_supported_properties_reach_membership_unchanged():
    fields = [{"key": "a", "kind": "choice", "label": "A", "required": True, "options": ["x", "y"]}]
    fake = FakeCheck()
    await suggest(server(), fake, form_key="f", fields=fields, **ID)
    assert fake.requests[1]["json"]["proposal"]["forms"][0]["fields"] == fields


# ---------------------------------------------------------------- invalid forms are rejected by Membership's verdict

@pytest.mark.asyncio
async def test_a_form_membership_rejects_is_an_error_with_its_messages():
    issues = [
        {"code": "WF_FORM_FIELD", "severity": "ERROR", "path": "/forms/f/kind", "message": "A choice field needs options"},
        {"code": "WF_FORM_SCHEMA", "severity": "ERROR", "path": "/forms/f", "message": "Form schema is not a valid Phase 1 JSON Schema subset"},
        {"code": "WF_FORM_REF", "severity": "ERROR", "path": "/nodes/1/form", "message": "No published form f"},
    ]
    fields = [{"key": "kind", "kind": "choice", "label": "T"}]
    result = await suggest(server(), FakeCheck(issues=issues), form_key="f", fields=fields, **ID)
    assert result.is_error and result.error_code == "FORM_SUGGESTION_INVALID"
    o = out(result)
    assert o["valid"] is False and o["saved"] is False
    assert [i["message"] for i in o["issues"]] == ["A choice field needs options", "Form schema is not a valid Phase 1 JSON Schema subset"]


# ---------------------------------------------------------------- invalid parameters

@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {}, {"form_key": "f"}, {"fields": LEAVE_FIELDS},
    {"form_key": "", "fields": LEAVE_FIELDS}, {"form_key": "  ", "fields": LEAVE_FIELDS}, {"form_key": 5, "fields": LEAVE_FIELDS},
    {"form_key": "x" * 201, "fields": LEAVE_FIELDS}, {"form_key": "f", "form_name": 3, "fields": LEAVE_FIELDS},
    {"form_key": "f", "fields": []}, {"form_key": "f", "fields": "reason"}, {"form_key": "f", "fields": ["reason"]},
    {"form_key": "f", "fields": [{"key": 1, "kind": "text"}]}, {"form_key": "f", "fields": [{"key": "a", "kind": "text", "required": "yes"}]},
    {"form_key": "f", "fields": [{"key": "a", "kind": "choice", "options": "x"}]},
    {"form_key": "f", "fields": [{"key": f"k{i}", "kind": "text"} for i in range(51)]},
])
async def test_invalid_parameters_are_rejected_without_calling_membership(arguments):
    fake = FakeCheck()
    result = await suggest(server(), fake, **arguments, **ID)
    assert result.is_error and result.error_code == "INVALID_PARAMS" and not fake.requests


# ---------------------------------------------------------------- identity and permission

@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [{}, {"auth_token": TOKEN}, {"tenant_id": 7}, {"auth_token": " ", "tenant_id": 7}, {"auth_token": TOKEN, "tenant_id": 0}])
async def test_a_missing_identity_fails_before_membership_is_used(identity):
    fake = FakeCheck()
    result = await suggest(server(), fake, **LEAVE, **identity)
    assert result.is_error and result.error_code == "IDENTITY_REQUIRED" and not fake.requests


@pytest.mark.asyncio
async def test_a_caller_membership_refuses_is_refused_at_the_probe_and_no_form_is_checked():
    fake = FakeCheck(status=403)
    result = await suggest(server(), fake, **LEAVE, **ID)
    assert result.is_error and result.error_code == "FORBIDDEN" and TOKEN not in result.content
    assert len(fake.requests) == 1 and fake.requests[0]["json"]["proposal"]["forms"] == []


# ---------------------------------------------------------------- downstream failures

@pytest.mark.asyncio
@pytest.mark.parametrize("fake", [FakeCheck(status=500), FakeCheck(body={"unexpected": True}), FakeCheck(body={"forms": [], "issues": []})])
async def test_membership_failing_or_answering_oddly_is_a_check_failure_not_a_valid_form(fake):
    result = await suggest(server(), fake, **LEAVE, **ID)
    assert result.is_error and result.error_code == "CHECK_FAILED"


@pytest.mark.asyncio
async def test_a_failure_on_the_second_request_after_a_passing_probe_is_a_check_failure():
    class SecondFails(FakeCheck):
        async def __call__(self, method, url, headers, request_params, timeout):
            if request_params["json"]["proposal"]["forms"]:
                self.status = 500
            return await super().__call__(method, url, headers, request_params, timeout)
    result = await suggest(server(), SecondFails(), **LEAVE, **ID)
    assert result.is_error and result.error_code == "CHECK_FAILED"


# ---------------------------------------------------------------- duplicate field keys and lost fields

DUP_FIELDS = [
    {"key": "reason", "kind": "text", "label": "Reason", "required": True},
    {"key": "reason", "kind": "textarea", "label": "Reason (details)"},
    {"key": "days", "kind": "number", "label": "Days"},
]


@pytest.mark.asyncio
async def test_fields_sharing_a_key_are_never_reported_as_a_valid_form():
    # Membership folds same-key fields into one and reports no issue; the compiled form here does the same
    result = await suggest(server(), FakeCheck(), form_key="f", fields=DUP_FIELDS, **ID)
    assert result.is_error and result.error_code == "FORM_SUGGESTION_INVALID"
    o = out(result)
    assert o["valid"] is False and o["saved"] is False
    assert [i["code"] for i in o["issues"]] == ["FORM_FIELD_DUPLICATE"] and "'reason'" in o["issues"][0]["message"]


@pytest.mark.asyncio
async def test_a_field_missing_from_the_checked_form_is_reported_not_silently_dropped():
    class Drops(FakeCheck):
        async def __call__(self, method, url, headers, request_params, timeout):
            response = await super().__call__(method, url, headers, request_params, timeout)
            data = response.json()
            if data.get("forms"):
                data["forms"][0]["formSchema"]["properties"].pop("days", None)
            return httpx.Response(200, json=data, request=httpx.Request(method, url))
    result = await suggest(server(), Drops(), **LEAVE, **ID)
    assert result.is_error and out(result)["issues"][0]["code"] == "FORM_FIELD_LOST"


@pytest.mark.asyncio
async def test_distinct_keys_still_give_a_valid_form():
    result = await suggest(server(), FakeCheck(), **LEAVE, **ID)
    assert not result.is_error and out(result)["valid"] is True
