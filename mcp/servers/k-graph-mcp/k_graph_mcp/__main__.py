"""Process entrypoint for the K-Graph MCP server."""

from __future__ import annotations

import os
from typing import Literal, cast

from .runtime import create_runtime_from_env


def main() -> None:
  transport = os.getenv("MCP_TRANSPORT", "streamable-http")
  if transport not in {"stdio", "sse", "streamable-http"}:
    raise ValueError(
      "MCP_TRANSPORT must be stdio, sse, or streamable-http"
    )

  runtime = create_runtime_from_env()
  try:
    runtime.mcp.run(
      transport=cast(
        Literal["stdio", "sse", "streamable-http"],
        transport,
      )
    )
  finally:
    runtime.close()


if __name__ == "__main__":
  main()
