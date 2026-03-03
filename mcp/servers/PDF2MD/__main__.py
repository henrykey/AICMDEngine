#!/usr/bin/env python3
"""MCP server entry point for PDF2MD"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

if __name__ == "__main__":
    # DEBUG: Write to log file
    debug_log = "/tmp/pdf2md_debug.log"
    def log(msg):
        with open(debug_log, "a") as f:
            f.write(f"{msg}\n")
        print(msg, file=sys.stderr, flush=True)

    # Load .env file from PDF2MD directory
    env_path = Path(__file__).parent / '.env'
    log(f"[DEBUG __main__] env_path: {env_path}")
    log(f"[DEBUG __main__] env_path exists: {env_path.exists()}")

    load_dotenv(env_path)

    # Check if VLM env vars are loaded
    vlm_provider = os.getenv("VLM_MODEL_PROVIDER")
    qwen_api_key = os.getenv("QWEN_API_KEY")
    allow_vlm = os.getenv("PDF2MD_ALLOW_EXTERNAL_VLM")

    log(f"[DEBUG __main__] VLM_MODEL_PROVIDER: {vlm_provider}")
    log(f"[DEBUG __main__] QWEN_API_KEY: {qwen_api_key[:20] if qwen_api_key else None}...")
    log(f"[DEBUG __main__] PDF2MD_ALLOW_EXTERNAL_VLM: {allow_vlm}")

    from .server import mcp
    mcp.run()
