#!/usr/bin/env python3
"""环境诊断脚本"""
import sys
import os

print("=" * 80)
print("环境诊断")
print("=" * 80)
print()

# Python 环境
print(f"Python 路径: {sys.executable}")
print(f"Python 版本: {sys.version}")
print(f"当前工作目录: {os.getcwd()}")
print()

# 检查 websockets
try:
    import websockets
    print(f"✓ websockets 已安装: v{websockets.__version__}")
except ImportError:
    print("✗ websockets 未安装")
    sys.exit(1)

# 检查 aiohttp
try:
    import aiohttp
    print(f"✓ aiohttp 已安装: v{aiohttp.__version__}")
except ImportError:
    print("✗ aiohttp 未安装")
    sys.exit(1)

# 检查 pdf2image
try:
    import pdf2image
    print(f"✓ pdf2image 已安装")
except ImportError:
    print("✗ pdf2image 未安装")

print()

# 检查端口连接
import socket
def check_port(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

print("端口连接检查:")
if check_port('127.0.0.1', 8000):
    print("  ✓ 端口 8000 可连接")
else:
    print("  ✗ 端口 8000 不可连接")

if check_port('127.0.0.1', 8080):
    print("  ✓ 端口 8080 可连接")
else:
    print("  ✗ 端口 8080 不可连接")

print()

# 测试登录
import asyncio
import aiohttp

async def test_login():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:8000/v1/auth/login",
                json={"username": "admin", "password": "admin123"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    token = data['access_token']
                    print(f"✓ 登录成功, token 长度: {len(token)}")
                    return token
                else:
                    print(f"✗ 登录失败: HTTP {resp.status}")
                    return None
    except Exception as e:
        print(f"✗ 登录异常: {e}")
        return None

async def test_ws(token):
    try:
        async with websockets.connect(f"ws://localhost:8000/mcp/v1?token={token}") as ws:
            print("✓ WebSocket 连接成功")
            await ws.close()
            return True
    except Exception as e:
        print(f"✗ WebSocket 连接失败: {e}")
        return False

print()
print("连接测试:")
token = asyncio.run(test_login())
if token:
    asyncio.run(test_ws(token))

print()
print("=" * 80)
