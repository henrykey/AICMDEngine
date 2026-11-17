"""
Tests for form_mcp.find_forms, the read-only form tool reached through the MCP Router.

The Membership HTTP layer is replaced at the request-sending step, so the real HTTPClient builds the real Authorization and
X-Tenant-ID headers; no real Membership or Router is involved here (see the report for what was run against the real Router).
"""

import base64
import json
import time

import httpx
import pytest
from unittest.mock import patch

from src.mcp.registry import MCPRegistry
from src.mcp_servers.form_mcp import FORM_MCP

LEAVE = {
    "formKey": "leave_request", "formName": "Leave request", "version": 2, "status": "published",
    "formSchema": {
        "type": "object", "required": ["reason", "days"],
        "properties": {
            "reason": {"type": "string", "title": "Reason"},
            "start_date": {"type": "string", "title": "Start", "format": "date"},
            "days": {"type": "number", "title": "Days"},
        },
    },
}
EXPENSE = {"formKey": "expense_claim", "formName": "Expense claim", "version": 1, "status": "draft", "formSchema": {"type": "object"}}


def _jwt(exp_in=3600):
    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': int(time.time()) + exp_in, 'sub': '1'})}.sig"


TOKEN = _jwt()


class FakeMembership:
    """Stands in for GET /v2/forms: pages of a fixed list, and records what the request carried."""

    def __init__(self, forms, total=None, status=200):
        self.forms, self.total, self.status, self.requests = forms, total, status, []

    async def __call__(self, method, url, headers, request_params, timeout):
        self.requests.append({"method": method, "url": str(url), "headers": dict(headers), "params": dict(request_params)})
        request = httpx.Request(method, url)
        if self.status >= 400:
            return httpx.Response(self.status, json={"message": "no"}, request=request)
        query = request_params.get("params") or request_params.get("query") or {}
        page, size = int(query.get("page", 1)), int(query.get("page_size", 20))
        chunk = self.forms[(page - 1) * size: page * size]
        total = len(self.forms) if self.total is None else self.total
        return httpx.Response(200, json={"data": chunk, "meta": {"page": page, "page_size": size, "total": total}}, request=request)


@pytest.fixture
def mcp():
    return FORM_MCP(membership_base_url="http://membership.test")


async def call(mcp, fake, **kwargs):
    with patch("src.services.http_client.HTTPClient._send_request", new=fake):
        return await mcp.execute_tool("find_forms", **kwargs)


def body(result):
    return json.loads(result.content)


# ---------------------------------------------------------------- discovery

def test_the_tool_is_discoverable_through_the_registry(mcp):
    registry = MCPRegistry()
    registry.register_mcp(mcp)
    info = registry.get_tool_info("form_mcp", "find_forms")
    assert info is not None
    props = info["input_schema"]["properties"]
    assert {"query", "auth_token", "tenant_id"} <= set(props)
    assert "find_forms" in [t["name"] for t in registry.get_mcp_info("form_mcp")["tools"]]


# ---------------------------------------------------------------- valid calls

@pytest.mark.asyncio
async def test_a_leave_form_is_found_with_a_summary_of_its_fields(mcp):
    fake = FakeMembership([EXPENSE, LEAVE])
    registry = MCPRegistry()
    registry.register_mcp(mcp)
    with patch("src.services.http_client.HTTPClient._send_request", new=fake):
        result = await registry.execute_command("form_mcp", "find_forms", query="leave", auth_token=TOKEN, tenant_id=7)
    assert not result.is_error
    out = body(result)
    assert out["total"] == 2 and out["matched"] == 1
    form = out["forms"][0]
    assert (form["formKey"], form["status"], form["version"]) == ("leave_request", "published", 2)
    fields = {f["key"]: f for f in form["fields"]}
    assert fields["days"]["required"] is True and fields["start_date"]["required"] is False
    assert fields["start_date"]["format"] == "date" and fields["reason"]["title"] == "Reason"


@pytest.mark.asyncio
async def test_the_request_carries_the_callers_own_token_and_tenant(mcp):
    fake = FakeMembership([LEAVE])
    await call(mcp, fake, auth_token=TOKEN, tenant_id=7)
    sent = fake.requests[0]
    assert sent["method"] == "GET" and sent["url"].endswith("/v2/forms")
    assert sent["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert sent["headers"]["X-Tenant-ID"] == "7"


@pytest.mark.asyncio
async def test_no_query_lists_the_forms_and_a_query_with_no_match_is_an_empty_list_not_an_error(mcp):
    assert body(await call(mcp, FakeMembership([LEAVE, EXPENSE]), auth_token=TOKEN, tenant_id=7))["matched"] == 2
    nothing = await call(mcp, FakeMembership([LEAVE, EXPENSE]), query="payroll", auth_token=TOKEN, tenant_id=7)
    assert not nothing.is_error and body(nothing) == {"total": 2, "matched": 0, "forms": []}


@pytest.mark.asyncio
async def test_every_page_is_read_before_answering(mcp):
    forms = [{"formKey": f"f{i:03d}", "formName": f"Form {i}", "version": 1, "status": "draft", "formSchema": {}} for i in range(230)]
    fake = FakeMembership(forms)
    out = body(await call(mcp, fake, query="f2", auth_token=TOKEN, tenant_id=7))
    assert len(fake.requests) == 3 and out["total"] == 230
    assert out["matched"] == 30 and len(out["forms"]) == 20  # f200..f229 match, and the answer is capped at 20


# ---------------------------------------------------------------- invalid parameters

@pytest.mark.asyncio
@pytest.mark.parametrize("query", [123, ["leave"], "x" * 201])
async def test_an_invalid_query_is_rejected_without_calling_membership(mcp, query):
    fake = FakeMembership([LEAVE])
    result = await call(mcp, fake, query=query, auth_token=TOKEN, tenant_id=7)
    assert result.is_error and result.error_code == "INVALID_PARAMS" and not fake.requests


# ---------------------------------------------------------------- identity and tenant

@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [
    {}, {"auth_token": TOKEN}, {"tenant_id": 7}, {"auth_token": "  ", "tenant_id": 7}, {"auth_token": TOKEN, "tenant_id": 0},
    {"auth_token": TOKEN, "tenant_id": "abc"}, {"auth_token": TOKEN, "tenant_id": True}, {"auth_token": TOKEN, "tenant_id": -3},
])
async def test_a_missing_or_unusable_identity_fails_and_nothing_is_read(mcp, identity):
    fake = FakeMembership([LEAVE])
    result = await call(mcp, fake, **identity)
    assert result.is_error and result.error_code == "IDENTITY_REQUIRED" and not fake.requests


@pytest.mark.asyncio
async def test_no_fixed_identity_is_used_even_when_the_server_was_built_with_one(mcp):
    mcp.auth_token, mcp.tenant_id = TOKEN, 1  # a stray attribute must not become a fallback
    fake = FakeMembership([LEAVE])
    result = await call(mcp, fake)
    assert result.is_error and result.error_code == "IDENTITY_REQUIRED" and not fake.requests


@pytest.mark.asyncio
async def test_a_tenant_in_the_query_text_cannot_change_the_tenant_sent(mcp):
    fake = FakeMembership([LEAVE])
    await call(mcp, fake, query="tenant_id=1", auth_token=TOKEN, tenant_id=7)
    assert fake.requests[0]["headers"]["X-Tenant-ID"] == "7"


# ---------------------------------------------------------------- errors

@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(403, "FORBIDDEN"), (500, "FORMS_FAILED")])
async def test_a_membership_refusal_or_failure_is_an_error_not_an_empty_answer(mcp, status, code):
    result = await call(mcp, FakeMembership([LEAVE], status=status), auth_token=TOKEN, tenant_id=7)
    assert result.is_error and result.error_code == code
    assert TOKEN not in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize("fake", [
    FakeMembership([LEAVE], total=5),        # the total is never reached: nothing new on the next page
])
async def test_a_list_that_cannot_be_read_completely_gives_no_answer(mcp, fake):
    result = await call(mcp, fake, auth_token=TOKEN, tenant_id=7)
    assert result.is_error and result.error_code == "FORMS_INCOMPLETE"


@pytest.mark.asyncio
async def test_a_response_without_a_total_gives_no_answer(mcp):
    class NoTotal(FakeMembership):
        async def __call__(self, method, url, headers, request_params, timeout):
            return httpx.Response(200, json={"data": [LEAVE]}, request=httpx.Request(method, url))
    result = await call(mcp, NoTotal([LEAVE]), auth_token=TOKEN, tenant_id=7)
    assert result.is_error and result.error_code == "FORMS_INCOMPLETE"
