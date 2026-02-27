#!/usr/bin/env python3
import argparse
import asyncio
import os
import sys

from .server import mcp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDF2MD MCP server")
    parser.add_argument("--http", action="store_true", help="Use streamable HTTP transport")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host")
    parser.add_argument("--port", type=int, default=8030, help="HTTP port")
    return parser.parse_args()


async def async_main() -> None:
    args = _parse_args()
    if not args.http and (args.host != "127.0.0.1" or args.port != 8030):
        print("Host/port are only valid with --http", file=sys.stderr)
        sys.exit(2)

    if args.http:
        await mcp.run_async(transport="streamable-http", host=args.host, port=args.port)
    else:
        await mcp.run_async()


def main() -> None:
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
