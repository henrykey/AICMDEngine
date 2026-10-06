"""Provider thinking defaults, matching Membership Admin UI's Chat Completions mapping."""
import re
from urllib.parse import urlparse


def normalize_thinking_mode(mode):
    if mode is None:
        return "default"
    if not isinstance(mode, str):
        raise ValueError("Thinking must be a preset or an effort name")
    value = mode.strip().lower() or "default"
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", value):
        raise ValueError("Thinking must start with a letter and use up to 32 letters, digits, _ or -")
    return value


def thinking_parameters(base_url, model, mode):
    mode = normalize_thinking_mode(mode)
    if mode == "default":
        return {}
    host = (urlparse(base_url).hostname or "").lower()
    model = (model or "").lower()
    disabled = mode in {"disabled", "none"}
    preset = mode == "enabled" or disabled
    kimi = host in {"api.moonshot.cn", "api.moonshot.ai", "api.kimi.com", "api.kimi.ai"}
    glm = host in {"api.z.ai", "open.bigmodel.cn"}
    if (kimi and model.startswith("kimi-k3")) or (glm and model.startswith("glm-5.3")):
        if disabled:
            raise ValueError("This model requires thinking and cannot disable it")
        if mode == "enabled":
            return {}
        if mode not in {"low", "high", "max"}:
            raise ValueError("This model supports thinking effort low, high or max")
        return {"reasoning_effort": mode}
    if host == "api.deepseek.com" or kimi or glm:
        params = {"thinking": {"type": "disabled" if disabled else "enabled"}}
        if not preset:
            params["reasoning_effort"] = mode
        return params
    if host == "dashscope.aliyuncs.com" or host.endswith(".aliyuncs.com") or host == "maas.qwencloudapi.com":
        params = {"enable_thinking": not disabled}
        if not preset:
            params["reasoning_effort"] = mode
        return params
    return {"reasoning_effort": "none" if disabled else "medium" if mode == "enabled" else mode}
