from __future__ import annotations

import base64
import hashlib
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ResolvedSource:
    source_path: str
    source_type: str
    source_ref: Optional[str]
    size_bytes: int
    sha1: str


class PDFSourceResolver:
    DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 120
    DEFAULT_MAX_BYTES = 500 * 1024 * 1024

    def __init__(self, root: Path) -> None:
        self._root = root
        self._uploads = self._root / "uploads"
        self._uploads.mkdir(parents=True, exist_ok=True)
        self._download_timeout = self.DEFAULT_DOWNLOAD_TIMEOUT_SECONDS
        self._max_bytes = self.DEFAULT_MAX_BYTES

    def resolve(
        self,
        task_name: str,
        file_path: Optional[str] = None,
        file_data: Optional[str] = None,
        file_url: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        s3_key: Optional[str] = None,
        storage_config: Optional[Dict[str, Any]] = None,
    ) -> ResolvedSource:
        source_count = sum(
            [
                bool(file_path),
                bool(file_data),
                bool(file_url),
                bool(s3_bucket or s3_key),
            ]
        )
        if source_count != 1:
            raise ValueError("exactly one source is required: file_path, file_data, file_url, or s3_bucket+s3_key")
        if bool(s3_bucket) != bool(s3_key):
            raise ValueError("s3_bucket and s3_key must be provided together")

        if file_data:
            return self._from_base64(task_name, file_data)
        if file_path:
            path = Path(file_path).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"file_path does not exist: {path}")
            return self._resolved_existing_file(path, "file_path", str(path))
        if file_url:
            return self._from_url(task_name, file_url)
        if s3_bucket and s3_key:
            return self._from_s3(task_name, s3_bucket, s3_key, storage_config)

        raise ValueError("no supported source was provided")

    def _from_base64(self, task_name: str, file_data: str) -> ResolvedSource:
        raw = base64.b64decode(file_data)
        self._validate_size(len(raw))
        digest = hashlib.sha1(raw).hexdigest()
        path = self._target_path(task_name, digest)
        path.write_bytes(raw)
        return ResolvedSource(str(path), "file_data", None, len(raw), digest)

    def _from_url(self, task_name: str, file_url: str) -> ResolvedSource:
        parsed = urllib.parse.urlparse(file_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("file_url must use http or https")
        safe_ref = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        with urllib.request.urlopen(file_url, timeout=self._download_timeout) as response:
            raw = self._read_limited(response)
        digest = hashlib.sha1(raw).hexdigest()
        path = self._target_path(task_name, digest)
        path.write_bytes(raw)
        return ResolvedSource(str(path), "file_url", safe_ref, len(raw), digest)

    def _from_s3(
        self,
        task_name: str,
        bucket: str,
        key: str,
        storage_config: Optional[Dict[str, Any]],
    ) -> ResolvedSource:
        self._validate_bucket(bucket)
        self._validate_s3_key(key)
        cfg = storage_config or {}
        endpoint = self._optional_str(cfg.get("endpoint"))
        region = self._optional_str(cfg.get("region")) or "us-east-1"
        access_key = self._optional_str(cfg.get("access_key"))
        secret_key = self._optional_str(cfg.get("secret_key"))
        path_style = self._bool_value(cfg.get("path_style"), False)
        if not access_key or not secret_key:
            raise ValueError("storage_config.access_key and storage_config.secret_key are required for s3 source")

        try:
            import boto3  # type: ignore
            from botocore.config import Config  # type: ignore
        except Exception as exc:
            raise RuntimeError("boto3 is required for s3 direct source") from exc

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path" if path_style else "virtual"}),
        )
        obj = client.get_object(Bucket=bucket, Key=key)
        raw = self._read_limited(obj["Body"])
        digest = hashlib.sha1(raw).hexdigest()
        path = self._target_path(task_name, digest)
        path.write_bytes(raw)
        return ResolvedSource(str(path), "s3", f"{bucket}/{key}", len(raw), digest)

    def _resolved_existing_file(self, path: Path, source_type: str, source_ref: str) -> ResolvedSource:
        size = path.stat().st_size
        self._validate_size(size)
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        return ResolvedSource(str(path), source_type, source_ref, size, digest)

    def _read_limited(self, stream) -> bytes:
        chunks = []
        total = 0
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            self._validate_size(total)
            chunks.append(chunk)
        return b"".join(chunks)

    def _target_path(self, task_name: str, digest: str) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_name).strip("._") or "pdf"
        return self._uploads / f"{safe_name}_{digest[:12]}.pdf"

    def _validate_size(self, size: int) -> None:
        if size <= 0:
            raise ValueError("source PDF is empty")
        if size > self._max_bytes:
            raise ValueError(f"source PDF exceeds max bytes: {size} > {self._max_bytes}")

    def _validate_bucket(self, bucket: str) -> None:
        if not bucket or "/" in bucket or "\\" in bucket:
            raise ValueError("invalid s3_bucket")

    def _validate_s3_key(self, key: str) -> None:
        if not key or key.startswith("/") or "\x00" in key:
            raise ValueError("invalid s3_key")
        if any(part == ".." for part in key.split("/")):
            raise ValueError("s3_key must not contain path traversal")

    def _optional_str(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _bool_value(self, value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
