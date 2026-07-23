"""FastMCP entry point for legacy document conversion."""

from __future__ import annotations

import os

from fastmcp import FastMCP

from .converter import (
    convert_doc_base64_to_docx,
    convert_doc_to_docx as convert_word_document,
)


mcp = FastMCP("docs-converter")


@mcp.tool
def convert_doc_to_docx(
    source_path: str | None = None,
    output_path: str | None = None,
    overwrite: bool = False,
    input_data: str | None = None,
    filename: str = "document.doc",
) -> dict:
  """Convert a legacy binary Word .doc file into a .docx file."""
  if input_data is not None:
    return convert_doc_base64_to_docx(input_data, filename)
  if source_path is None:
    return {
        "success": False,
        "source_path": None,
        "output_path": None,
        "error_code": "SOURCE_NOT_FOUND",
        "message": "source_path or input_data is required",
    }
  return convert_word_document(source_path, output_path, overwrite)


def run_server() -> None:
  transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
  if transport == "stdio":
    mcp.run(transport="stdio")
    return

  host = os.getenv("MCP_HOST", "0.0.0.0")
  port = int(os.getenv("MCP_PORT", "9012"))
  if transport == "sse":
    mcp.run(transport="sse", host=host, port=port, path="/sse")
    return
  if transport == "streamable-http":
    mcp.run(transport="streamable-http", host=host, port=port, path="/mcp")
    return
  raise ValueError(f"Unsupported MCP_TRANSPORT: {transport}")
