#!/usr/bin/env python3
"""MCP server entry point for PDF2MD"""

from .server import mcp

if __name__ == "__main__":
    mcp.run()
