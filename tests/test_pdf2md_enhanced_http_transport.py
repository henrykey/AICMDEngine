import importlib.util
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server import http as fastmcp_http
from starlette.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT_PATH = ROOT / "mcp/servers/PDF2MDEnhanced/http_transport.py"
DOCKERFILE_PATHS = [
    ROOT / "mcp/servers/PDF2MDEnhanced/Dockerfile",
    ROOT / "mcp/servers/PDF2MDEnhanced/Dockerfile.cn",
]


def _load_transport_module():
    spec = importlib.util.spec_from_file_location(
        "pdf2md_enhanced_http_transport_test", TRANSPORT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_pdf2md_streamable_http_accepts_10_mib_and_rejects_over_16_mib():
    transport = _load_transport_module()
    original_manager = fastmcp_http.FastMCPStreamableHTTPSessionManager
    transport.configure_pdf2md_http_request_limit()

    try:
        server = FastMCP(name="pdf2md-http-limit-test")
        app = server.http_app(path="/mcp", stateless_http=True)
        headers = {"content-type": "application/json"}

        with TestClient(app) as client:
            accepted = client.post(
                "/mcp", content=b" " * (10 * 1024 * 1024), headers=headers
            )
            rejected = client.post(
                "/mcp", content=b" " * (16 * 1024 * 1024 + 1), headers=headers
            )

        assert accepted.status_code != 413
        assert rejected.status_code == 413
    finally:
        fastmcp_http.FastMCPStreamableHTTPSessionManager = original_manager


def test_all_pdf2md_images_copy_the_http_transport_module():
    for dockerfile_path in DOCKERFILE_PATHS:
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        assert "COPY __init__.py __main__.py http_transport.py" in dockerfile
