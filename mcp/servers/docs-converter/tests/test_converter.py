from pathlib import Path
import base64
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch
import zipfile

from docs_converter.converter import convert_doc_base64_to_docx, convert_doc_to_docx


OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def write_doc(path: Path) -> None:
  path.write_bytes(OLE_SIGNATURE + b"test content")


def successful_run(command, **kwargs):
  source = Path(command[-1])
  output_dir = Path(command[-2])
  converted = output_dir / f"{source.stem}.docx"
  with zipfile.ZipFile(converted, "w") as archive:
    archive.writestr("[Content_Types].xml", "<Types/>")
    archive.writestr("word/document.xml", "<document/>")
  return CompletedProcess(command, 0, stdout="convert ok", stderr="")


def test_convert_doc_to_docx_success(tmp_path):
  source = tmp_path / "sample.doc"
  write_doc(source)

  with patch("docs_converter.converter.subprocess.run", side_effect=successful_run):
    result = convert_doc_to_docx(str(source))

  assert result["success"] is True
  assert result["output_path"] == str(tmp_path / "sample.docx")
  with zipfile.ZipFile(result["output_path"]) as archive:
    assert "word/document.xml" in archive.namelist()
  assert source.read_bytes().startswith(OLE_SIGNATURE)


def test_missing_source_has_stable_error(tmp_path):
  result = convert_doc_to_docx(str(tmp_path / "missing.doc"))

  assert result["success"] is False
  assert result["error_code"] == "SOURCE_NOT_FOUND"


def test_rejects_non_doc_extension(tmp_path):
  source = tmp_path / "sample.docx"
  source.write_bytes(b"PK\x03\x04")

  result = convert_doc_to_docx(str(source))

  assert result["success"] is False
  assert result["error_code"] == "UNSUPPORTED_FORMAT"


def test_rejects_fake_doc(tmp_path):
  source = tmp_path / "fake.doc"
  source.write_text("not an OLE document")

  result = convert_doc_to_docx(str(source))

  assert result["success"] is False
  assert result["error_code"] == "INVALID_SOURCE"


def test_does_not_overwrite_by_default(tmp_path):
  source = tmp_path / "sample.doc"
  output = tmp_path / "sample.docx"
  write_doc(source)
  output.write_bytes(b"existing")

  result = convert_doc_to_docx(str(source))

  assert result["success"] is False
  assert result["error_code"] == "OUTPUT_EXISTS"
  assert output.read_bytes() == b"existing"


def test_overwrite_replaces_only_after_success(tmp_path):
  source = tmp_path / "sample.doc"
  output = tmp_path / "sample.docx"
  write_doc(source)
  output.write_bytes(b"existing")

  with patch("docs_converter.converter.subprocess.run", side_effect=successful_run):
    result = convert_doc_to_docx(str(source), overwrite=True)

  assert result["success"] is True
  with zipfile.ZipFile(output) as archive:
    assert "word/document.xml" in archive.namelist()


def test_timeout_leaves_no_output(tmp_path):
  source = tmp_path / "sample.doc"
  write_doc(source)

  with patch(
      "docs_converter.converter.subprocess.run",
      side_effect=TimeoutExpired(cmd=["soffice"], timeout=1),
  ):
    result = convert_doc_to_docx(str(source), timeout_seconds=1)

  assert result["success"] is False
  assert result["error_code"] == "CONVERSION_TIMEOUT"
  assert not (tmp_path / "sample.docx").exists()


def test_nonzero_exit_has_stable_error(tmp_path):
  source = tmp_path / "sample.doc"
  write_doc(source)
  failed = CompletedProcess(["soffice"], 1, stdout="", stderr="conversion failed")

  with patch("docs_converter.converter.subprocess.run", return_value=failed):
    result = convert_doc_to_docx(str(source))

  assert result["success"] is False
  assert result["error_code"] == "CONVERSION_FAILED"
  assert "conversion failed" in result["message"]


def test_success_without_output_is_failure(tmp_path):
  source = tmp_path / "sample.doc"
  write_doc(source)
  completed = CompletedProcess(["soffice"], 0, stdout="", stderr="")

  with patch("docs_converter.converter.subprocess.run", return_value=completed):
    result = convert_doc_to_docx(str(source))

  assert result["success"] is False
  assert result["error_code"] == "OUTPUT_NOT_CREATED"


def test_convert_base64_doc_to_base64_docx():
  source = OLE_SIGNATURE + b"test content"

  with patch("docs_converter.converter.subprocess.run", side_effect=successful_run):
    result = convert_doc_base64_to_docx(
        base64.b64encode(source).decode("ascii"),
        "legacy.doc",
    )

  assert result["success"] is True
  assert result["source_filename"] == "legacy.doc"
  assert result["output_filename"] == "legacy.docx"
  converted = base64.b64decode(result["output_base64"])
  assert converted.startswith(b"PK")


def test_convert_base64_rejects_invalid_base64():
  result = convert_doc_base64_to_docx("not base64!", "legacy.doc")

  assert result["success"] is False
  assert result["error_code"] == "INVALID_BASE64"


def test_convert_base64_rejects_non_doc_filename():
  result = convert_doc_base64_to_docx(
      base64.b64encode(OLE_SIGNATURE).decode("ascii"),
      "legacy.docx",
  )

  assert result["success"] is False
  assert result["error_code"] == "UNSUPPORTED_FORMAT"
