import asyncio

from docs_converter.main import mcp


def test_only_expected_tool_is_registered():
  tools = asyncio.run(mcp.list_tools())

  assert [tool.name for tool in tools] == ["convert_doc_to_docx"]
