#!/usr/bin/env python3
"""MCP server entry point for PDF2MD"""

from pathlib import Path
from dotenv import load_dotenv

if __name__ == "__main__":
    # Load .env file from PDF2MD directory
    env_path = Path(__file__).parent / '.env'
    load_dotenv(env_path)

    from .server import mcp
    mcp.run()
