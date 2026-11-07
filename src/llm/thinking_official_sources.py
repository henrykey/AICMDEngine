"""Fetch bounded public documentation from fixed official source addresses."""

from urllib.parse import urlsplit, urljoin, unquote
from html.parser import HTMLParser
import re
import asyncio

import httpx


OFFICIAL_SOURCES = {
    "api.deepseek.com": "https://api-docs.deepseek.com/guides/thinking_mode/",
    "api.openai.com": "https://developers.openai.com/api/docs/guides/reasoning?api-mode=chat",
    "dashscope.aliyuncs.com": "https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions",
    "dashscope-intl.aliyuncs.com": "https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions",
    "dashscope-us.aliyuncs.com": "https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions",
    "api.z.ai": "https://docs.z.ai/guides/capabilities/thinking",
    "open.bigmodel.cn": "https://docs.bigmodel.cn/cn/guide/capabilities/thinking",
}
MAX_DOCUMENT_BYTES = 512 * 1024
MAX_SOURCE_PAGES = 5
OFFICIAL_INDEXES = {
    "open.bigmodel.cn": "https://docs.bigmodel.cn/llms.txt",
    "api.z.ai": "https://docs.z.ai/llms.txt",
    "api.deepseek.com": "https://api-docs.deepseek.com/llms.txt",
    "api.openai.com": "https://developers.openai.com/api/docs/llms.txt",
}


def normalize_source(document):
    """Cross-language v1 normalization; hash the original decoded text separately."""
    value = re.sub(r"<(script|style|noscript)(?=[ \t\r\n\f/>])[^>]*>.*?</\1[ \t\r\n\f]*>", " ", document, flags=re.I | re.S | re.ASCII)
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"[ \t\r\n\f]+", " ", value).strip(" \t\r\n\f")
OFFICIAL_REPOSITORY_FILES = {
    "open.bigmodel.cn": (
        "https://raw.githubusercontent.com/zai-org/GLM-V/main/skills/glmv-prompt-gen/scripts/prompt_gen.py",
        "https://raw.githubusercontent.com/zai-org/GLM-V/main/skills/glmv-caption/scripts/glmv_caption.py",
    ),
}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls.extend(value for key, value in attrs if key == "href" and value)


def _safe_official_link(url, allowed_host):
    try:
        parsed = urlsplit(url)
        decoded = unquote(parsed.path)
        if (parsed.scheme != "https" or parsed.hostname != allowed_host or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment or "%" in decoded
                or any(part in {".", ".."} for part in decoded.split("/")) or "\\" in decoded
                or any(ord(c) < 32 for c in decoded)):
            return False
        return bool(decoded) and not decoded.lower().endswith((".png", ".jpg", ".pdf", ".zip"))
    except (ValueError, TypeError):
        return False


def is_official_source(base_url, source_url):
    try:
        host = urlsplit(base_url).hostname.lower()
        primary = OFFICIAL_SOURCES.get(host)
        if not primary:
            return False
        if source_url == primary or source_url == OFFICIAL_INDEXES.get(host):
            return True
        if source_url in OFFICIAL_REPOSITORY_FILES.get(host, ()):
            return True
        return _safe_official_link(source_url, urlsplit(primary).hostname)
    except (ValueError, TypeError, AttributeError):
        return False


async def _fetch_fixed(url, transport=None):
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, trust_env=False, transport=transport) as client:
            async with client.stream("GET", url) as response:
                content_type = response.headers.get("content-type", "").lower()
                if response.status_code != 200 or not content_type.startswith(("text/html", "text/plain", "text/markdown")):
                    return None
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_DOCUMENT_BYTES:
                        return None
                    chunks.append(chunk)
                document = b"".join(chunks).decode("utf-8", errors="replace")
                return {"url": url, "document": document} if document.strip() else None
    except (ValueError, TypeError, httpx.HTTPError, httpx.InvalidURL):
        return None


async def _fetch_official_sources(base_url, model, transport=None, sources=None):
    """Follow a small number of relevant links within an explicitly trusted provider site."""
    try:
        endpoint = urlsplit(base_url)
        host = (endpoint.hostname or "").lower()
        if (endpoint.scheme != "https" or host not in OFFICIAL_SOURCES or endpoint.username or endpoint.password
                or endpoint.query or endpoint.fragment or endpoint.port not in (None, 443)):
            return []
    except (TypeError, ValueError):
        return []
    primary = await fetch_official_source(base_url, transport)
    allowed_host = urlsplit(OFFICIAL_SOURCES[host]).hostname
    if sources is None:
        sources = []
    if primary:
        sources.append(primary)
    index_url = OFFICIAL_INDEXES.get(host)
    if index_url:
        index = await _fetch_fixed(index_url, transport)
        if index:
            sources.append(index)
    for repo_url in OFFICIAL_REPOSITORY_FILES.get(host, ()):
        repo = await _fetch_fixed(repo_url, transport)
        # A trusted repository is a source candidate only when it actually mentions
        # the exact model; trust in a file is not model-family membership.
        model_pattern = r"(?<![a-z0-9._-])" + re.escape(str(model or "")) + r"(?![a-z0-9._-])"
        if repo and model and re.search(model_pattern, repo["document"], re.I):
            sources.append(repo)
    candidates = []
    for source in tuple(sources):
        if urlsplit(source["url"]).hostname != allowed_host:
            continue
        links = _Links()
        links.feed(source["document"])
        links.urls.extend(re.findall(r"\]\((https://[^\s)]+)\)", source["document"]))
        for link in links.urls:
            url = urljoin(source["url"], link)
            if _safe_official_link(url, allowed_host) and url not in {item["url"] for item in sources}:
                candidates.append(url)
    # URL ranking only selects pages to read; it never asserts model membership or support.
    model_name = str(model or "").lower()
    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=lambda url: (model_name not in url.lower(), not any(x in url.lower() for x in ("thinking", "reasoning", "model"))))
    for url in candidates[:max(0, MAX_SOURCE_PAGES - len(sources))]:
        result = await _fetch_fixed(url, transport)
        if result:
            sources.append(result)
    return sources


async def fetch_official_sources(base_url, model, transport=None):
    sources = []
    try:
        async with asyncio.timeout(25):
            return await _fetch_official_sources(base_url, model, transport, sources)
    except TimeoutError:
        return sources


async def fetch_official_source(base_url, transport=None):
    try:
        endpoint = urlsplit(base_url)
        if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password
                or endpoint.query or endpoint.fragment or endpoint.port not in (None, 443)):
            return None
        url = OFFICIAL_SOURCES.get(endpoint.hostname.lower())
        if not url:
            return None
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, trust_env=False, transport=transport) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    return None
                content_type = response.headers.get("content-type", "").lower()
                if not content_type.startswith(("text/html", "text/plain", "text/markdown")):
                    return None
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_DOCUMENT_BYTES:
                        return None
                    chunks.append(chunk)
        text = b"".join(chunks).decode("utf-8", errors="replace")
        return {"url": url, "document": text} if text.strip() else None
    except (ValueError, TypeError, httpx.HTTPError, httpx.InvalidURL):
        return None
