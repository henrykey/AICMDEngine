"""
Tests for the machine-readable result of the membership lookup_org / lookup_role tools.

The default result is the readable English sentence existing consumers see; response_format="json" returns one JSON object
(contract membership.directory_lookup.v1) so a caller can tell a unique match from no match, several matches and an error.
"""

import json

import pytest
from unittest.mock import patch

from src.mcp_servers.membership_mcp import MembershipMCPServer

ORGS = [
    {"id": 10, "name": "Finance", "code": "FIN", "type": "DEPARTMENT"},
    {"id": 11, "name": "Sales", "code": "SAL", "type": "DEPARTMENT"},
]
ROLES = [
    {"id": 20, "name": "Head", "code": "HEAD", "org_id": 10},
    {"id": 21, "name": "Head", "code": "HEAD2", "org_id": 11},
    {"id": 22, "name": "Clerk", "code": "CLERK", "org_id": 11},
]


class _Forbidden(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = type("R", (), {"status_code": status})()


def _payload(result):
    return json.loads(result.content)


@pytest.mark.asyncio
class TestDirectoryLookupContract:

    def setup_method(self):
        self.mcp = MembershipMCPServer(tenant_id=7)

    async def test_the_default_result_is_still_the_readable_sentence(self):
        result = await self.mcp.execute_tool("lookup_org", query="Finance", orgs=ORGS)

        assert result.is_error is False
        assert result.content == "Resolved organization 'Finance' to ID 10"
        assert result.data["org_id"] == 10

    async def test_json_unique_match_has_status_id_match_and_a_readable_message(self):
        result = await self.mcp.execute_tool("lookup_org", query="Finance", orgs=ORGS, response_format="json")

        body = _payload(result)
        assert result.is_error is False
        assert body["contract"] == "membership.directory_lookup.v1"
        assert (body["kind"], body["status"], body["id"]) == ("org", "unique", 10)
        assert body["match"] == {"id": 10, "name": "Finance"}
        assert body["message"] == "Resolved organization 'Finance' to ID 10"
        assert result.data == body

    async def test_json_no_match_is_an_error_result_with_status_none_and_no_id(self):
        result = await self.mcp.execute_tool("lookup_org", query="Legal", orgs=ORGS, response_format="json")

        body = _payload(result)
        assert result.is_error is True and result.error_code == "ORG_NOT_FOUND"
        assert body["status"] == "none" and "id" not in body and body["candidates"] == []
        assert body["message"] == "No organization matched query 'Legal'"

    async def test_json_several_matches_list_the_candidates_and_name_no_id(self):
        result = await self.mcp.execute_tool("lookup_role", query="Head", roles=ROLES, response_format="json")

        body = _payload(result)
        assert result.is_error is True and result.error_code == "MULTIPLE_ROLE_MATCHES"
        assert body["status"] == "multiple" and "id" not in body
        assert body["candidates"] == [{"id": 20, "name": "Head", "orgId": 10}, {"id": 21, "name": "Head", "orgId": 11}]

    async def test_json_unique_role_carries_its_unit(self):
        result = await self.mcp.execute_tool("lookup_role", query="Clerk", roles=ROLES, response_format="json")

        body = _payload(result)
        assert (body["kind"], body["status"], body["id"]) == ("role", "unique", 22)
        assert body["match"] == {"id": 22, "name": "Clerk", "orgId": 11}

    async def test_the_message_follows_the_requested_language_and_defaults_to_english(self):
        zh = _payload(await self.mcp.execute_tool("lookup_org", query="Finance", orgs=ORGS, response_format="json", language="zh"))
        zh_none = _payload(await self.mcp.execute_tool("lookup_org", query="Legal", orgs=ORGS, response_format="json", language="zh-CN"))
        other = _payload(await self.mcp.execute_tool("lookup_org", query="Finance", orgs=ORGS, response_format="json", language="fr"))

        assert zh["message"] == "已将组织“Finance”解析为 ID 10"
        assert zh_none["message"] == "没有组织匹配“Legal”"
        assert other["message"] == "Resolved organization 'Finance' to ID 10"
        # the machine-readable fields do not depend on the language
        assert (zh["status"], zh["id"]) == (other["status"], other["id"]) == ("unique", 10)

    async def test_json_a_read_that_is_forbidden_is_an_error_status_not_no_match(self):
        with patch("src.services.http_client.HTTPClient.execute", side_effect=_Forbidden(403)):
            result = await self.mcp.execute_tool("lookup_org", query="Finance", response_format="json",
                                                 auth_token="t", tenant_id=7)

        body = _payload(result)
        assert result.is_error is True
        assert body["status"] == "error" and body["error"] == {"code": "forbidden"} and "id" not in body
        assert body["message"] == "Not allowed to read organizations"

    async def test_json_any_other_failure_is_an_error_status_and_leaks_no_detail(self):
        with patch("src.services.http_client.HTTPClient.execute", side_effect=RuntimeError("secret detail")):
            result = await self.mcp.execute_tool("lookup_role", query="Head", response_format="json",
                                                 auth_token="t", tenant_id=7)

        body = _payload(result)
        assert body["status"] == "error" and body["error"] == {"code": "failed"}
        assert "secret detail" not in result.content

    async def test_json_without_a_caller_identity_is_an_error_status_and_reads_nothing(self):
        with patch("src.services.http_client.HTTPClient.execute") as execute:
            result = await MembershipMCPServer().execute_tool("lookup_org", query="Finance", response_format="json")

        assert _payload(result)["error"] == {"code": "unauthenticated"}
        execute.assert_not_called()

    async def test_json_reads_the_directory_with_the_callers_token_and_tenant_only(self):
        with patch("src.services.http_client.HTTPClient.execute", return_value={"data": ORGS, "meta": {"total": 2}}) as execute:
            result = await self.mcp.execute_tool("lookup_org", query="Finance", response_format="json",
                                                 auth_token="caller-token", tenant_id=7)

        assert _payload(result)["id"] == 10
        kwargs = execute.call_args.kwargs
        assert kwargs["command"] == "GET /v2/orgs"
        assert kwargs["auth_token"] == "caller-token" and kwargs["tenant_id"] == 7

    async def test_a_blank_query_is_an_error_status(self):
        result = await self.mcp.execute_tool("lookup_org", query="  ", orgs=ORGS, response_format="json")

        assert result.is_error is True and _payload(result)["error"] == {"code": "empty"}

    async def test_the_new_arguments_are_declared_so_the_router_passes_them_on(self):
        for name in ("lookup_org", "lookup_role"):
            properties = self.mcp.get_tool(name).input_schema["properties"]
            assert properties["response_format"]["enum"] == ["text", "json"]
            assert properties["language"]["default"] == "en"


    # ------------------------------------------------------------------ completeness of the directory read

    @staticmethod
    def _page(items, total):
        return {"data": items, "meta": {"page": 1, "page_size": 100, "total": total, "total_pages": 1}}

    async def _lookup(self, tool, query, responses_or_error, **extra):
        with patch("src.services.http_client.HTTPClient.execute", side_effect=responses_or_error) as execute:
            result = await self.mcp.execute_tool(tool, query=query, response_format="json", auth_token="t", tenant_id=7, **extra)
        return result, execute

    async def test_the_last_page_completes_the_read_and_the_match_may_be_on_it(self):
        first = [{"id": i, "name": f"Unit {i}"} for i in range(1, 101)]
        second = [{"id": 101, "name": "Finance"}] + [{"id": 200 + i, "name": f"Other {i}"} for i in range(29)]
        result, execute = await self._lookup("lookup_org", "Finance", [self._page(first, 130), self._page(second, 130)])

        body = _payload(result)
        assert (body["status"], body["id"]) == ("unique", 101)
        assert [c.kwargs["params"]["query"]["page"] for c in execute.call_args_list] == [1, 2]
        assert execute.call_args_list[0].kwargs["params"]["query"]["page_size"] == 100

    async def test_a_single_page_that_holds_the_whole_total_is_complete_and_an_empty_directory_has_no_match(self):
        result, execute = await self._lookup("lookup_org", "Finance", [self._page(ORGS, 2)])
        assert _payload(result)["status"] == "unique" and execute.call_count == 1

        result, execute = await self._lookup("lookup_org", "Finance", [self._page([], 0)])
        assert _payload(result)["status"] == "none" and execute.call_count == 1

    async def test_the_page_bound_with_more_data_behind_it_is_incomplete_even_when_a_match_was_read(self):
        pages = []
        for p in range(20):
            items = [{"id": p * 100 + i + 1, "name": f"Unit {p * 100 + i + 1}"} for i in range(100)]
            pages.append(self._page(items, 5000))
        pages[0]["data"][0]["name"] = "Finance"          # one exact match is among what was read
        result, execute = await self._lookup("lookup_org", "Finance", pages)

        body = _payload(result)
        assert result.is_error is True and result.error_code == "LOOKUP_ORG_INCOMPLETE"
        assert body["status"] == "error" and body["error"] == {"code": "incomplete"} and "id" not in body
        assert execute.call_count == 20            # the bound holds: nothing is read beyond it
        assert body["message"].startswith("The list of organizations could not be read completely")

    async def test_an_endpoint_that_ignores_paging_and_has_more_than_it_returned_is_incomplete(self):
        page = [{"id": i, "name": f"Role {i}"} for i in range(1, 201)]
        result, execute = await self._lookup("lookup_role", "Nobody", [self._page(page, 250), self._page(page, 250), self._page(page, 250)])

        body = _payload(result)
        assert body["status"] == "error" and body["error"] == {"code": "incomplete"}
        assert execute.call_count == 2             # the repeated page ends the read

    async def test_an_error_on_a_later_page_is_a_failure_not_an_answer_from_the_pages_before_it(self):
        first = [{"id": 1, "name": "Finance"}] + [{"id": i, "name": f"Unit {i}"} for i in range(2, 101)]
        result, execute = await self._lookup("lookup_org", "Finance", [self._page(first, 130), RuntimeError("boom secret")])

        body = _payload(result)
        assert result.is_error is True and body["status"] == "error" and body["error"] == {"code": "failed"}
        assert "id" not in body and "secret" not in result.content
        assert execute.call_count == 2

    async def test_a_forbidden_later_page_is_reported_as_forbidden(self):
        first = [{"id": i, "name": f"Unit {i}"} for i in range(1, 101)]
        result, _ = await self._lookup("lookup_org", "Unit 5", [self._page(first, 130), _Forbidden(403)])

        assert _payload(result)["error"] == {"code": "forbidden"}

    async def test_a_list_without_a_readable_total_or_with_a_changing_total_is_incomplete(self):
        no_meta, _ = await self._lookup("lookup_org", "Finance", [{"data": ORGS}])
        bad_total, _ = await self._lookup("lookup_org", "Finance", [self._page(ORGS, "2")])
        negative, _ = await self._lookup("lookup_org", "Finance", [self._page(ORGS, -1)])
        first = [{"id": i, "name": f"Unit {i}"} for i in range(1, 101)]
        changing, _ = await self._lookup("lookup_org", "Finance", [self._page(first, 130), self._page(first[:5], 131)])

        for result in (no_meta, bad_total, negative, changing):
            assert _payload(result)["error"] == {"code": "incomplete"}

    async def test_the_default_text_result_is_also_never_an_answer_from_part_of_the_data(self):
        first = [{"id": i, "name": f"Unit {i}"} for i in range(1, 101)]
        with patch("src.services.http_client.HTTPClient.execute", side_effect=[self._page(first, 5000)] * 20) as execute:
            result = await self.mcp.execute_tool("lookup_org", query="Unit 7", auth_token="t", tenant_id=7)
        assert result.is_error is True and result.error_code == "LOOKUP_ORG_INCOMPLETE"
        assert not result.content.startswith(("Resolved", "No organization matched", "Multiple"))
        assert execute.call_count == 2             # the repeated page ends the read

        with patch("src.services.http_client.HTTPClient.execute", return_value=self._page(ORGS, 2)):
            ok = await self.mcp.execute_tool("lookup_org", query="Finance", auth_token="t", tenant_id=7)
        assert ok.is_error is False and ok.content == "Resolved organization 'Finance' to ID 10"

        with patch("src.services.http_client.HTTPClient.execute", return_value={"data": ORGS}):
            roles = await self.mcp.execute_tool("lookup_role", query="Head", auth_token="t", tenant_id=7)
        assert roles.is_error is True and roles.error_code == "LOOKUP_ROLE_INCOMPLETE"
