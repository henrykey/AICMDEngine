from __future__ import annotations

from typing import Any

from fastmcp.server import http as fastmcp_http
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings


PDF2MD_HTTP_MAX_REQUEST_BODY_SIZE = 16 * 1024 * 1024


class PDF2MDStreamableHTTPSessionManager(
    fastmcp_http.FastMCPStreamableHTTPSessionManager
):
    """FastMCP session manager with PDF2MD's explicit request body limit."""

    def __init__(
        self,
        app: Any,
        event_store: EventStore | None = None,
        json_response: bool = False,
        stateless: bool = False,
        security_settings: TransportSecuritySettings | None = None,
        retry_interval: int | None = None,
    ) -> None:
        self._shared_event_store: EventStore | None = None
        StreamableHTTPSessionManager.__init__(
            self,
            app=app,
            event_store=event_store,
            json_response=json_response,
            stateless=stateless,
            security_settings=security_settings,
            retry_interval=retry_interval,
            max_request_body_size=PDF2MD_HTTP_MAX_REQUEST_BODY_SIZE,
        )


def configure_pdf2md_http_request_limit() -> None:
    fastmcp_http.FastMCPStreamableHTTPSessionManager = (
        PDF2MDStreamableHTTPSessionManager
    )
