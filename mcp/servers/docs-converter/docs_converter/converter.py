"""Core conversion functions for legacy Word documents."""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
from uuid import uuid4
import zipfile


OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
DEFAULT_TIMEOUT_SECONDS = 120


def _failure(
    source_path: Path,
    error_code: str,
    message: str,
    output_path: Path | None = None,
) -> dict[str, Any]:
  return {
      "success": False,
      "source_path": str(source_path),
      "output_path": str(output_path) if output_path else None,
      "error_code": error_code,
      "message": message,
  }


def _is_ole_document(path: Path) -> bool:
  try:
    with path.open("rb") as source_file:
      return source_file.read(len(OLE_SIGNATURE)) == OLE_SIGNATURE
  except OSError:
    return False


def _is_docx_document(path: Path) -> bool:
  try:
    with zipfile.ZipFile(path) as archive:
      names = set(archive.namelist())
      return "[Content_Types].xml" in names and "word/document.xml" in names
  except (OSError, zipfile.BadZipFile):
    return False


def convert_doc_to_docx(
    source_path: str,
    output_path: str | None = None,
    overwrite: bool = False,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
  """Convert a legacy binary Word .doc file to .docx with LibreOffice."""
  source = Path(source_path).expanduser().resolve()

  if not source.exists() or not source.is_file():
    return _failure(source, "SOURCE_NOT_FOUND", "Source document does not exist")
  if source.suffix.lower() != ".doc":
    return _failure(source, "UNSUPPORTED_FORMAT", "Source document must use the .doc extension")
  if not _is_ole_document(source):
    return _failure(source, "INVALID_SOURCE", "Source is not a valid OLE binary document")

  output = (
      Path(output_path).expanduser().resolve()
      if output_path
      else source.with_suffix(".docx")
  )
  if output.suffix.lower() != ".docx":
    return _failure(
        source,
        "UNSUPPORTED_FORMAT",
        "Output document must use the .docx extension",
        output,
    )
  if not output.parent.exists() or not output.parent.is_dir():
    return _failure(source, "OUTPUT_NOT_WRITABLE", "Output directory does not exist", output)
  if output.exists() and not overwrite:
    return _failure(source, "OUTPUT_EXISTS", "Output document already exists", output)
  if not os.access(output.parent, os.W_OK):
    return _failure(source, "OUTPUT_NOT_WRITABLE", "Output directory is not writable", output)

  soffice = shutil.which("soffice") or shutil.which("libreoffice")
  if not soffice:
    return _failure(
        source,
        "CONVERSION_FAILED",
        "LibreOffice executable was not found",
        output,
    )

  try:
    with tempfile.TemporaryDirectory(prefix="docs-converter-") as temp_dir_name:
      temp_dir = Path(temp_dir_name)
      profile_uri = (temp_dir / "profile").as_uri()
      command = [
          soffice,
          "--headless",
          "--nologo",
          "--nodefault",
          "--nofirststartwizard",
          f"-env:UserInstallation={profile_uri}",
          "--convert-to",
          "docx",
          "--outdir",
          str(temp_dir),
          str(source),
      ]
      completed = subprocess.run(
          command,
          capture_output=True,
          text=True,
          timeout=timeout_seconds,
          check=False,
      )
      if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        return _failure(
            source,
            "CONVERSION_FAILED",
            f"LibreOffice conversion failed: {detail}",
            output,
        )

      converted = temp_dir / f"{source.stem}.docx"
      if not converted.is_file() or not _is_docx_document(converted):
        return _failure(
            source,
            "OUTPUT_NOT_CREATED",
            "LibreOffice did not create a valid OOXML .docx output",
            output,
        )

      staged_output = output.parent / f".{output.name}.{uuid4().hex}.tmp"
      try:
        shutil.copyfile(converted, staged_output)
        os.replace(staged_output, output)
      finally:
        if staged_output.exists():
          staged_output.unlink()

  except subprocess.TimeoutExpired:
    return _failure(
        source,
        "CONVERSION_TIMEOUT",
        f"LibreOffice conversion exceeded {timeout_seconds} seconds",
        output,
    )
  except OSError as exc:
    return _failure(source, "CONVERSION_FAILED", f"Conversion failed: {exc}", output)

  return {
      "success": True,
      "source_path": str(source),
      "output_path": str(output),
      "converter": "libreoffice",
      "warnings": [],
  }


def convert_doc_base64_to_docx(input_data: str, filename: str = "document.doc") -> dict[str, Any]:
  """Convert Base64-encoded legacy Word bytes and return Base64 DOCX bytes."""
  try:
    source_bytes = base64.b64decode(input_data, validate=True)
  except (binascii.Error, ValueError, TypeError):
    return {
        "success": False,
        "source_path": None,
        "output_path": None,
        "error_code": "INVALID_BASE64",
        "message": "input_data must be valid Base64",
    }

  safe_name = Path(filename).name
  if not safe_name.lower().endswith(".doc"):
    return {
        "success": False,
        "source_path": None,
        "output_path": None,
        "error_code": "UNSUPPORTED_FORMAT",
        "message": "filename must use the .doc extension",
    }

  with tempfile.TemporaryDirectory(prefix="docs-converter-input-") as temp_dir_name:
    temp_dir = Path(temp_dir_name)
    source = temp_dir / safe_name
    output = source.with_suffix(".docx")
    source.write_bytes(source_bytes)

    result = convert_doc_to_docx(str(source), str(output))
    if not result.get("success"):
      result["source_path"] = None
      result["output_path"] = None
      return result

    return {
        "success": True,
        "source_filename": safe_name,
        "output_filename": output.name,
        "output_base64": base64.b64encode(output.read_bytes()).decode("ascii"),
        "converter": result.get("converter"),
        "warnings": result.get("warnings", []),
    }
