from __future__ import annotations

import base64
import json
from typing import Optional

from fastapi import Request


def extract_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def extract_user_id(request: Request, auth_token: Optional[str] = None) -> Optional[str]:
    header_user_id = request.headers.get("X-User-ID")
    if header_user_id:
        return header_user_id

    token = auth_token or extract_bearer_token(request)
    if not token:
        return None

    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_part = parts[1]
        payload_part += "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_part.encode("utf-8")).decode("utf-8"))
    except Exception:
        return None

    for key in ("user_id", "member_id", "uid", "sub"):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.isdigit():
            return value

    return None
