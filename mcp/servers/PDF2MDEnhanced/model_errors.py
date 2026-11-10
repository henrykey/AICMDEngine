from typing import Optional


def model_error_code(exc: Exception) -> Optional[str]:
    """Classify provider errors without exposing upstream payloads."""
    current = exc
    seen = set()
    status = None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        body = getattr(current, "body", None)
        error = body.get("error", body) if isinstance(body, dict) else {}
        code = str(error.get("code", "")).lower() if isinstance(error, dict) else ""
        if code in {"insufficient_quota", "billing_hard_limit_reached"}:
            return "MODEL_QUOTA_EXHAUSTED"
        current_status = getattr(current, "status_code", None) or getattr(current, "code", None)
        if current_status in (401, 403):
            return "MODEL_AUTH_FAILED"
        if current_status == 429:
            status = "MODEL_RATE_LIMITED"
        current = current.__cause__ or current.__context__
    return status



def raise_model_error(exc: Exception) -> None:
    if model_error_code(exc):
        raise exc
