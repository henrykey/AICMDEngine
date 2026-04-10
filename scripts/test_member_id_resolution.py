#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import settings
from src.services.llm_client import llm_client


CONFIGURED_BASE_URL = settings.membership_service_url.rstrip("/")
BASE_URL = "http://localhost:8080" if "host.docker.internal" in CONFIGURED_BASE_URL else CONFIGURED_BASE_URL
TENANT_ID = "1"
USERNAME = "admin"
PASSWORD = "admin123"
MEMBER_ID = "1"


def login(username: str, password: str) -> str:
    login_resp = requests.post(
        f"{BASE_URL}/v2/auth/login",
        headers={
            "Content-Type": "application/json",
            "X-Tenant-ID": TENANT_ID,
        },
        json={"username": username, "password": password},
        timeout=15,
    )
    login_resp.raise_for_status()
    payload = login_resp.json()
    token = payload.get("access_token")
    if not token:
        raise ValueError(f"Login failed: {payload}")
    return token


def fetch_members(login_username: str, login_password: str) -> List[Dict[str, Any]]:
    token = login(login_username, login_password)
    members_resp = requests.get(
        f"{BASE_URL}/v2/members",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": TENANT_ID,
        },
        timeout=15,
    )
    members_resp.raise_for_status()
    payload = members_resp.json()
    members = payload.get("data", payload.get("members", []))
    if not isinstance(members, list):
        raise ValueError(f"Unexpected members payload: {payload}")
    return members


def reset_admin_password(login_username: str, login_password: str, password: str) -> Dict[str, Any]:
    token = login(login_username, login_password)
    response = requests.post(
        f"{BASE_URL}/v2/members/{MEMBER_ID}/password",
        headers={
            "Content-Type": "application/json",
            "X-Tenant-ID": TENANT_ID,
            "Authorization": f"Bearer {token}",
        },
        json={"newPassword": password},
        timeout=15,
    )
    return {
        "status_code": response.status_code,
        "body": response.text,
    }


async def ask_llm(members: List[Dict[str, Any]]) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You are given a list of member objects. "
                "Find the member whose username is exactly 'admin'. "
                "Return only JSON with keys member_id, username, fullName, reason."
            ),
        },
        {
            "role": "user",
            "content": (
                "Members:\n"
                f"{json.dumps(members, ensure_ascii=False, indent=2)}\n\n"
                "Question: 这个用户名为admin的id是多少？"
            ),
        },
    ]
    return await llm_client.generate_response(
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
        max_tokens=500,
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-admin-password", action="store_true")
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--login-username", default=USERNAME)
    parser.add_argument("--login-password", default=PASSWORD)
    args = parser.parse_args()

    if args.reset_admin_password:
        reset_result = reset_admin_password(args.login_username, args.login_password, args.password)
        print("reset_result:", json.dumps(reset_result, ensure_ascii=False, indent=2))
        return

    members = fetch_members(args.login_username, args.login_password)
    print("members_count:", len(members))
    print("members_preview:", json.dumps(members[:2], ensure_ascii=False, indent=2))
    llm_result = await ask_llm(members)
    print("llm_result:", llm_result)


if __name__ == "__main__":
    asyncio.run(main())
