#!/usr/bin/env python3
"""
Test MCP Router PDF extraction with JWT token
Tests random pages from scanned PDF to verify token propagation
"""

import asyncio
import websockets
import json
import sys
import random
import base64
from pathlib import Path

# MCP Router configuration
MCP_ROUTER_URL = "ws://localhost:8000/mcp/v1"
PDF_PATH = Path.home() / "Documents/GB/GB∕T 150.1~4-2024 压力容器 扫描版.pdf"

# Use admin JWT token (this is the token that should be propagated to MCP tools)
JWT_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJwZXJtaXNzaW9ucyI6WyJzeXN0ZW0uYWRtaW4iLCJzeXN0ZW0ucmVhZCIsInN5c3RlbS53cml0ZSIsInN5c3RlbS5kZWxldGUiLCJtZW1iZXIuYWRtaW4iLCJtZW1iZXIucmVhZCIsIm1lbWJlci53cml0ZSIsIm1lbWJlci5jcmVhdGUiLCJtZW1iZXIuZGVsZXRlIiwicm9sZS5hZG1pbiIsInJvbGUucmVhZCIsInJvbGUud3JpdGUiLCJyb2xlLmNyZWF0ZSIsInJvbGUuZGVsZXRlIiwicGVybWlzc2lvbi5hZG1pbiIsInBlcm1pc3Npb24ucmVhZCIsInBlcm1pc3Npb24ud3JpdGUiLCJwZXJtaXNzaW9uLmNyZWF0ZSIsInBlcm1pc3Npb24uZGVsZXRlIiwib3JnLmFkbWluIiwib3JnLnJlYWQiLCJvcmcud3JpdGUiLCJvcmcuY3JlYXRlIiwib3JnLmRlbGV0ZSIsImF1ZGl0LmFkbWluIiwiYXVkaXQucmVhZCIsImF1ZGl0LndyaXRlIiwiYXVkaXQuZGVsZXRlIiwidGVuYW50LmFkbWluIiwidGVuYW50LnJlYWQiLCJ0ZW5hbnQud3JpdGUiLCJ0ZW5hbnQuY3JlYXRlIiwidGVuYW50LmRlbGV0ZSIsIndvcmtmbG93LmFkbWluIiwid29ya2Zsb3cucmVhZCIsIndvcmtmbG93LndyaXRlIiwid29ya2Zsb3cuY3JlYXRlIiwid29ya2Zsb3cuZGVsZXRlIl0sInJvbGVzIjpbIlNVUEVSX0FETUlOIiwiUk9PVCJdLCJmdWxsTmFtZSI6IlN5c3RlbSBSb290IEFkbWluaXN0cmF0b3IiLCJpc1ZpcnR1YWwiOmZhbHNlLCJ0b2tlbl90eXBlIjoiYWNjZXNzIiwianVfdmVyc2lvbiI6MSwic3VwZXJBZG1pbiI6dHJ1ZSwibWVtYmVySWQiOjksInN0YXR1cyI6ImFjdGl2ZSIsInN1YiI6InJvb3QiLCJpYXQiOjE3NjY2MjYzMzIsImV4cCI6MTc2NjYyOTkyMH0.YTmVMUXFG9lGYc5JR3kfOLNpVQNQfhFYSvG-OMEGBJ"


async def test_mcp_pdf_extraction():
    """Test PDF extraction through MCP Router with JWT token"""

    # Check if PDF file exists
    if not PDF_PATH.exists():
        print(f"✗ PDF file not found: {PDF_PATH}")
        return

    # Randomly select number of pages to test (1-5)
    num_pages = random.randint(1, 5)
    print("=" * 80)
    print(f"MCP Router PDF Extraction Test (Random {num_pages} pages)")
    print("=" * 80)
    print(f"MCP Router URL: {MCP_ROUTER_URL}")
    print(f"PDF File: {PDF_PATH}")
    print(f"JWT Token: {JWT_TOKEN[:50]}... (length: {len(JWT_TOKEN)})")
    print()

    # Connect to MCP Router via WebSocket with token in query parameter
    ws_url = f"{MCP_ROUTER_URL}?token={JWT_TOKEN}"

    try:
        async with websockets.connect(ws_url) as websocket:
            print("✓ Connected to MCP Router")
            print()

            # Step 1: Initialize connection
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "test-client",
                        "version": "1.0.0"
                    }
                }
            }

            await websocket.send(json.dumps(init_request))
            print("→ Sent initialize request")

            init_response = json.loads(await websocket.recv())
            print(f"← Received: {json.dumps(init_response, indent=2)[:200]}...")
            print()

            # Step 2: List available tools
            tools_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list"
            }

            await websocket.send(json.dumps(tools_request))
            print("→ Sent tools/list request")

            tools_response = json.loads(await websocket.recv())
            tools = tools_response.get('result', {}).get('tools', [])
            print(f"← Received {len(tools)} tools")

            # Find PDF extraction tools
            pdf_tools = []
            for tool in tools:
                tool_name = tool.get('name', '')
                properties = tool.get('inputSchema', {}).get('properties', {})

                # Check if tool accepts file parameters
                if any(key in properties for key in ['file', 'filename', 'content', 'document']):
                    pdf_tools.append(tool)
                    print(f"  Found tool: {tool_name}")

            print()

            if not pdf_tools:
                print("✗ No PDF extraction tools found!")
                return

            # Step 3: Read PDF file
            print(f"→ Reading PDF file...")
            with open(PDF_PATH, 'rb') as f:
                pdf_data = f.read()
                pdf_base64 = base64.b64encode(pdf_data).decode('utf-8')
                pdf_size = len(pdf_data)

            print(f"  PDF file size: {pdf_size} bytes ({pdf_size / 1024 / 1024:.2f} MB)")
            print(f"  Base64 encoded size: {len(pdf_base64)} characters")
            print()

            # Step 4: Call the first PDF extraction tool
            tool = pdf_tools[0]
            tool_name = tool.get('name')

            print(f"→ Calling tool: {tool_name}")
            print("-" * 80)

            tool_call_request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {
                        "file": {
                            "name": PDF_PATH.name,
                            "content": pdf_base64,
                            "type": "application/pdf"
                        },
                        "jwt_token": JWT_TOKEN  # Pass JWT token to tool
                    }
                }
            }

            await websocket.send(json.dumps(tool_call_request))
            print("→ Sent tool/call request")
            print(f"   Tool: {tool_name}")
            print(f"   File: {PDF_PATH.name}")
            print(f"   Arguments: file (PDF), jwt_token (length: {len(JWT_TOKEN)})")
            print()

            # Receive response
            print("← Waiting for response...")
            response = json.loads(await websocket.recv())

            print("-" * 80)
            print(f"← Received response:")
            print(json.dumps(response, indent=2))
            print()

            # Check result
            if 'result' in response:
                result = response['result']
                content = result.get('content', [])

                if content and isinstance(content, list):
                    for item in content:
                        if item.get('type') == 'text':
                            text = item.get('text', '')
                            print(f"✓ Extraction successful!")
                            print(f"  Text length: {len(text)} characters")
                            print(f"  Preview (first 500 chars):")
                            print("  " + "-" * 50)
                            print("  " + text[:500])
                            if len(text) > 500:
                                print("  ...")
                            print("  " + "-" * 50)
                            return

                print("✓ Tool executed but no text content found")
                print(f"  Full result: {json.dumps(result, indent=2)}")
            elif 'error' in response:
                error = response['error']
                print(f"✗ Tool execution failed!")
                print(f"  Error code: {error.get('code')}")
                print(f"  Error message: {error.get('message')}")
                print(f"  Error data: {error.get('data', {})}")

    except websockets.exceptions.WebSocketException as e:
        print(f"✗ WebSocket error: {e}")
        print("\nTroubleshooting:")
        print("1. Check if MCP Router is running:")
        print("   curl http://localhost:8000/health")
        print("2. Check MCP Router logs")
        print("3. Verify MCP Router URL is correct")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_mcp_pdf_extraction())
