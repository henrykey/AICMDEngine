#!/usr/bin/env python3
"""MCP server entry point for PDF2MD"""

import argparse
import asyncio
from pathlib import Path
from dotenv import load_dotenv


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="PDF2MD MCP server - PDF to Markdown with VLM OCR support"
    )

    parser.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP transport instead of STDIO (suitable for remote deployment and multiple clients)."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address for HTTP mode (default: 127.0.0.1)."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9003,
        help="Port for HTTP mode (default: 9003)."
    )

    return parser.parse_args()


async def async_main() -> None:
    """Asynchronous main entry point."""
    args = _parse_args()

    # Load .env file from PDF2MD directory
    env_path = Path(__file__).parent / '.env'
    load_dotenv(env_path)

    # 支持两种运行方式：
    # 1. 作为模块运行：python -m PDF2MD.__main__（相对导入有效）
    # 2. 直接运行：python __main__.py（需要绝对导入）
    try:
        from .server import mcp
    except ImportError:
        # 相对导入失败，尝试绝对导入
        from server import mcp

    if args.http:
        # HTTP/SSE mode
        await mcp.run_async(
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )
    else:
        # STDIO mode (default)
        await mcp.run_async()


def main():
    """Main entry point."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
