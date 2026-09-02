import copy
import asyncio
import base64
import json
import sys
from pathlib import Path

import fitz
import pytest

from tests import test_pdf2md_enhanced_bad_text_policy as fixtures


processor = fixtures.page_processor
ledger = sys.modules[f"{fixtures.PACKAGE_NAME}.layout_ledger"]
VLMClient = sys.modules[f"{fixtures.PACKAGE_NAME}.vlm_client"].DynamicVLMClient
OCRClient = processor.OpenAICompatibleOcrClient
TABLE = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
PARTIAL = "<table><tr><td>SECRET_ORIGINAL_FRAGMENT"


@pytest.mark.parametrize("ocr_results,vlm_results,providers", [
    ([TABLE], [], ["glm_ocr"]),
    ([PARTIAL, TABLE], [], ["glm_ocr", "glm_ocr"]),
    ([PARTIAL, PARTIAL], [PARTIAL, TABLE], ["glm_ocr", "glm_ocr", "vlm_ocr", "vlm_ocr"]),
    ([RuntimeError("unavailable")], [TABLE], ["glm_ocr", "vlm_ocr"]),
    ([PARTIAL, PARTIAL], [PARTIAL, PARTIAL], ["glm_ocr", "glm_ocr", "vlm_ocr", "vlm_ocr"]),
])
def test_table_crop_ocr_first_and_bounded_smaller_retries(tmp_path, ocr_results, vlm_results, providers):
    source = tmp_path / "page.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1200, 1600), False)
    pix.clear_with(255)
    pix.save(str(source))
    raw = fixtures._layout_raw([
        {"label": "table", "bbox_2d": [10, 20, 90, 80], "content": PARTIAL},
    ])
    outcome = ledger.build_layout_outcome(raw, page_no=1, fallback_width=100, fallback_height=100)
    calls = []

    class OCR:
        enabled = True
        use_layout_parsing = True
        results = iter(ocr_results)

        def extract_table_html(self, path):
            image = fitz.Pixmap(path)
            calls.append(("glm_ocr", image.width, image.height))
            result = next(self.results)
            if isinstance(result, Exception):
                raise result
            return result

    class VLM(ContentClient):
        def extract_table_html(self, path, target, compact=False):
            image = fitz.Pixmap(path)
            calls.append(("vlm_ocr", image.width, image.height))
            return super().extract_table_html(path, target, compact)

    counts = processor._recover_layout_objects(
        source, tmp_path, outcome, ledger.recovery_blocks(outcome), VLM(vlm_results),
        bool(vlm_results), 8, 0.02, glm=OCR(), source_dpi=600,
    )
    assert [c[0] for c in calls] == providers
    assert calls[0][1] <= 300 and calls[0][2] <= 400
    for before, after in zip(calls, calls[1:]):
        assert after[1] <= before[1] and after[2] <= before[2]
        if before[0] == after[0]:
            assert after[1] < before[1] and after[2] < before[2]
    assert counts[:2] == (len(ocr_results), len(vlm_results))
    succeeds = (vlm_results or ocr_results)[-1] == TABLE
    assert outcome["layout"][0]["status"] == ("EXTRACTED" if succeeds else "FAILED")
    assert outcome["layout"][0]["bbox"] == [0.1, 0.2, 0.9, 0.8]
    if succeeds:
        assert outcome["payloads"]["tables"][0]["markdown"] == TABLE
    else:
        assert outcome["payloads"]["tables"] == []
        assert outcome["layout"][0]["review_required"] is True


@pytest.mark.parametrize("html", [TABLE, PARTIAL, f"```html\n{TABLE}\n```"])
def test_ocr_crop_keeps_raw_html_without_duplicate_markdown_projection(monkeypatch, html):
    client = OCRClient({"enabled": True, "model": "glm-ocr", "base_url": "http://127.0.0.1:1"})
    monkeypatch.setattr(client, "_call_layout_parsing_raw", lambda path: {
        "md_results": html, "layout_details": [[{"label": "table", "content": html}]],
    })
    result = client.extract_table_html("mock-crop.png")
    assert result == (TABLE if html.startswith("```") else html)
    assert result.count("<table>") == 1
    assert client.last_object_call_info["response_chars"] == len(html)


def test_ocr_crop_does_not_guess_between_multiple_tables(monkeypatch):
    client = OCRClient({"enabled": True, "model": "glm-ocr", "base_url": "http://127.0.0.1:1"})
    monkeypatch.setattr(client, "_call_layout_parsing_raw", lambda path: {
        "layout_details": [[{"label": "table", "content": TABLE}] * 2],
    })
    with pytest.raises(ValueError, match="ocr_crop_multiple_tables"):
        client.extract_table_html("mock-crop.png")


def test_ocr_crop_does_not_promote_nonempty_markdown_to_html(monkeypatch):
    client = OCRClient({"enabled": True, "model": "glm-ocr", "base_url": "http://127.0.0.1:1"})
    markdown = "| Col1 | Col2 |\n| --- | --- |\n| 1 | 2 |"
    monkeypatch.setattr(client, "_call_layout_parsing_raw", lambda path: {"md_results": markdown})
    assert client.extract_table_html("mock-crop.png") == ""
    assert client.last_object_call_info["json_status"] == "invalid"


@pytest.mark.parametrize("dpi,width,height", [(72, 600, 400), (150, 600, 400), (300, 300, 200), (650, 138, 92)])
def test_crop_caps_actual_pixels_without_upscaling(tmp_path, dpi, width, height):
    path = tmp_path / "page.png"
    source = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 400), False)
    source.clear_with(255)
    source.save(str(path))
    crop, info = processor._crop_layout_block_image(
        path, {"layout_id": "any-object", "bbox": [0, 0, 1, 1]}, tmp_path, source_dpi=dpi,
    )
    pixels = fitz.Pixmap(str(crop))
    assert (pixels.width, pixels.height) == (width, height)
    assert pixels.xres == min(dpi, 150)
    assert info["pixel_bbox"] == [0, 0, 600, 400]


def block(kind="table", number=1):
    return {
        "layout_id": f"p1-o{number:03d}-{kind}", "type": kind,
        "reading_order": number, "source_block_index": number * 10,
        "bbox": [0.1, 0.2, 0.9, 0.8], "content": PARTIAL if kind == "table" else "",
    }


def candidate(kind="table", number=1, **extra):
    payload = {"table": {"markdown": TABLE}, "formula": {"latex": r"x=\frac{a}{b}"},
               "figure": {"description": "Two pipes connected by a flexible joint."}}[kind]
    return {"layout_id": block(kind, number)["layout_id"], "type": kind,
            "status": "EXTRACTED", "complete": True, **payload, **extra}


@pytest.mark.parametrize("kind", ["table", "formula", "figure"])
def test_object_client_contract_is_crop_specific_budgeted_and_redacted(kind):
    client = VLMClient.__new__(VLMClient)
    client.max_tokens = 20000
    client.last_call_info = {}
    calls = []

    def mock_call(path, prompt, max_tokens):
        calls.append((path, prompt, max_tokens))
        client.last_call_info = {"mode": "stream", "finish_reason": "stop",
                                 "effective_max_tokens": max_tokens, "api_key": "SECRET_KEY"}
        return json.dumps(candidate(kind))

    client._call_image_prompt = mock_call
    result = client.extract_object_structured("crop.png", block(kind), compact=False)
    assert result == candidate(kind)
    assert calls[0][2] == 16384
    assert "already cropped" in calls[0][1]
    assert "metadata only" in calls[0][1]
    assert "SECRET_ORIGINAL_FRAGMENT" not in calls[0][1]
    assert "SECRET_KEY" not in json.dumps(client.last_object_call_info)
    assert client.last_object_call_info["json_status"] == "object"
    assert client.last_object_call_info["response_chars"] > 0
    assert client.last_object_call_info["finish_reason"] == "stop"


def test_object_client_never_raises_injected_budget_and_marks_invalid_json():
    client = VLMClient.__new__(VLMClient)
    client.max_tokens = 2048
    client.last_call_info = {"finish_reason": "length"}
    calls = []

    def mock_call(path, prompt, max_tokens):
        calls.append((prompt, max_tokens))
        return '{"layout_id": "truncated SECRET_RESPONSE'

    client._call_image_prompt = mock_call
    assert client.extract_object_structured("crop.png", block(), compact=True) == {}
    info = client.last_object_call_info
    assert calls[0][1] == 2048
    assert "compact" in calls[0][0].lower()
    assert info["json_status"] == "invalid"
    assert info["finish_reason"] is None  # previous call diagnostics must not leak
    assert "SECRET_RESPONSE" not in json.dumps(info)


def test_table_client_returns_fenced_html_without_json_wrapper():
    client = VLMClient.__new__(VLMClient)
    client.max_tokens = 20000
    client.last_call_info = {}
    calls = []

    def mock_call(path, prompt, max_tokens):
        calls.append((path, prompt, max_tokens))
        client.last_call_info = {"mode": "stream", "finish_reason": "stop", "effective_max_tokens": max_tokens}
        return f"```html\n{TABLE}\n```"

    client._call_image_prompt = mock_call

    assert client.extract_table_html("crop.png", block(), compact=False) == TABLE
    assert calls[0][2] == 16384
    assert "no JSON" in calls[0][1]
    assert client.last_object_call_info["json_status"] == "html"


@pytest.mark.parametrize("changes,reason", [
    ({"layout_id": "foreign"}, "layout_id_mismatch"),
    ({"type": "figure"}, "object_type_mismatch"),
    ({"status": "FAILED", "complete": False}, "provider_reported_incomplete"),
    ({"complete": False}, "provider_reported_incomplete"),
    ({"markdown": ""}, "table_content_empty"),
    ({"markdown": PARTIAL}, "table_html_unclosed"),
    ({"markdown": "<table><tr><td>x</tr></td></table>"}, "table_html_invalid"),
    ({"markdown": "<table></table>"}, "table_cells_missing"),
    ({"markdown": TABLE + TABLE}, "table_count_invalid"),
    ({"markdown": "description without table"}, "table_markdown_invalid"),
    ({"markdown": "Heading\n---\nNot a table"}, "table_markdown_invalid"),
    ({"markdown": "| A | B |\n| --- | --- |\n| 1 |"}, "table_markdown_invalid"),
])
def test_recovered_table_hard_validation(changes, reason):
    rejection, shape = ledger.validate_recovered_object(block(), candidate(**changes))
    assert rejection == reason
    assert "SECRET_ORIGINAL_FRAGMENT" not in json.dumps(shape)
    assert "foreign" not in json.dumps(shape)


@pytest.mark.parametrize("kind,payload,reason", [
    ("formula", {"latex": r"x=\frac{a}{b"}, "formula_unbalanced"),
    ("formula", {"latex": r"\begin{matrix}1&2"}, "formula_unbalanced"),
    ("formula", {"latex": "UNREADABLE"}, "formula_content_empty"),
    ("figure", {"description": "", "caption": "Figure 10"}, "figure_content_empty"),
    ("figure", {"description": "[UNREADABLE]"}, "figure_content_empty"),
    ("figure", {"description": "Figure 10"}, "figure_content_empty"),
])
def test_formula_and_figure_require_valid_content(kind, payload, reason):
    assert ledger.validate_recovered_object(block(kind), candidate(kind, **payload))[0] == reason


@pytest.mark.parametrize("kind", ["table", "formula", "figure"])
def test_valid_recovered_payloads_pass_without_rewriting(kind):
    item = candidate(kind)
    before = copy.deepcopy(item)
    reason, shape = ledger.validate_recovered_object(block(kind), item)
    assert reason == ""
    assert shape["candidate_chars"] > 0
    assert item == before


class ContentClient:
    enabled = True

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.last_call_info = {}
        self.last_object_call_info = {}

    def extract_object_structured(self, path, target, compact=False):
        self.calls.append((path, copy.deepcopy(target), compact))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        value, info = response if isinstance(response, tuple) else (response, {})
        self.last_object_call_info = {"response_chars": 42, "json_status": "object", **info}
        return value

    def extract_table_html(self, path, target, compact=False):
        self.calls.append((path, copy.deepcopy(target), compact))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        value, info = response if isinstance(response, tuple) else (response, {})
        self.last_object_call_info = {"response_chars": 42, "json_status": "html", **info}
        if isinstance(value, dict):
            return value.get("markdown", "")
        return value


def recover(monkeypatch, responses, kinds=("table",), max_objects=8, enabled=True, glm=None):
    raw = fixtures._layout_raw([
        {"index": i * 10, "label": kind, "bbox_2d": [10, 20, 90, 80],
         "content": PARTIAL if kind == "table" else ""}
        for i, kind in enumerate(kinds, 1)
    ])
    outcome = ledger.build_layout_outcome(raw, page_no=1, fallback_width=100, fallback_height=100)
    client = ContentClient(responses)
    crop_calls = []

    def crop(path, target, directory, padding_ratio, source_dpi):
        crop_calls.append(target["layout_id"])
        return Path("crop.png"), {"pixel_bbox": [8, 18, 92, 82], "width": 84, "height": 64}

    monkeypatch.setattr(processor, "_crop_layout_block_image", crop)
    monkeypatch.setattr(processor, "_shrink_recovery_image", lambda path, info, scale: (path, info))
    counts = processor._recover_layout_objects(
        image_path=Path("page.png"), output_dir=Path("/tmp"), layout_outcome=outcome,
        pending_blocks=ledger.recovery_blocks(outcome), vlm=client, vlm_enabled=enabled,
        max_objects=max_objects, padding_ratio=0.02,
        glm=glm,
    )
    return outcome, client, crop_calls, counts


@pytest.mark.parametrize("finish,expected_calls", [("length", 2), ("content_filter", 1)])
def test_ocr_finish_reason_overrides_closed_html(monkeypatch, finish, expected_calls):
    class OCR:
        enabled = True
        calls = 0

        def extract_table_html(self, path):
            self.calls += 1
            self.last_object_call_info = {"finish_reason": finish if self.calls == 1 else "stop"}
            return TABLE

    outcome, vlm, _, (ocr_calls, vlm_calls, diag) = recover(monkeypatch, [], glm=OCR())
    assert ocr_calls == expected_calls
    assert vlm_calls == 0 and vlm.calls == []
    assert outcome["layout"][0]["status"] == ("EXTRACTED" if finish == "length" else "FAILED")


def test_incomplete_crop_retries_once_compact_then_recovers_original_object(monkeypatch):
    outcome, client, crops, (glm_calls, vlm_calls, diagnostics) = recover(monkeypatch, [
        candidate(markdown=PARTIAL), candidate(),
    ])
    assert glm_calls == 0
    assert vlm_calls == 2
    assert crops == ["p1-o001-table"]
    assert [c[2] for c in client.calls] == [False, True]
    item = outcome["layout"][0]
    assert item["status"] == "EXTRACTED" and item["review_required"] is False
    assert item["bbox"] == [0.1, 0.2, 0.9, 0.8] and item["reading_order"] == 1
    assert outcome["payloads"]["tables"][0]["markdown"] == TABLE
    attempts = diagnostics["objects"][0]["attempts"]
    assert [a["reason"] for a in attempts] == ["table_html_unclosed", "validated_object"]
    assert attempts[0]["candidate_chars"] == len(PARTIAL)
    assert attempts[0]["table_open_count"] == 1 and attempts[0]["table_close_count"] == 0
    assert "SECRET_ORIGINAL_FRAGMENT" not in json.dumps(diagnostics)


def test_table_recovery_adds_ledger_metadata_to_plain_html(monkeypatch):
    outcome, client, _, (_, calls, diagnostics) = recover(monkeypatch, [TABLE])

    assert calls == 1
    assert client.calls[0][2] is False
    payload = outcome["payloads"]["tables"][0]
    assert payload["markdown"] == TABLE
    assert payload["layout_id"] == "p1-o001-table"
    assert payload["source"] == "glm_ocr_layout+vlm_object_crop"
    assert diagnostics["objects"][0]["attempts"][0]["json_status"] == "html"


def test_two_invalid_crops_stay_failed_and_do_not_block_formula_or_figure(monkeypatch):
    outcome, client, _, (_, vlm_calls, diagnostics) = recover(monkeypatch, [
        candidate(markdown=PARTIAL), candidate(markdown=PARTIAL),
        candidate("formula", 2), candidate("figure", 3),
    ], kinds=("table", "formula", "figure"))
    assert vlm_calls == 4
    assert [b["status"] for b in outcome["layout"]] == ["FAILED", "EXTRACTED", "EXTRACTED"]
    assert outcome["layout"][0]["content"] == PARTIAL
    assert outcome["layout"][0]["review_required"] is True
    assert outcome["payloads"]["tables"] == []
    assert len(outcome["payloads"]["formulas"]) == len(outcome["payloads"]["figures"]) == 1
    assert diagnostics["objects"][0]["outcome"] == "failed"


def test_layout_table_with_synthetic_placeholder_columns_requires_crop_recovery():
    raw = fixtures._layout_raw([{
        "index": 10,
        "label": "table",
        "bbox_2d": [10, 20, 90, 80],
        "content": "| 参数 | 数值 | Col3 | Col4 |\n"
                   "| --- | --- | --- | --- |\n"
                   "| 0.35 | 1.480 |  |  |",
    }])

    outcome = ledger.build_layout_outcome(raw, page_no=1, fallback_width=100, fallback_height=100)

    assert outcome["layout"][0]["status"] == "FAILED"
    assert outcome["layout"][0]["error"]["code"] == "layout_table_synthetic_columns"
    assert [item["layout_id"] for item in ledger.recovery_blocks(outcome)] == ["p1-o001-table"]


def test_length_finish_reason_rejects_even_closed_valid_json(monkeypatch):
    outcome, _, _, (_, count, diagnostics) = recover(monkeypatch, [
        (candidate(), {"finish_reason": "length", "truncated": True}),
        (candidate(), {"finish_reason": "length", "truncated": True}),
    ])
    assert count == 2
    assert outcome["payloads"]["tables"] == []
    assert all(a["reason"] == "provider_output_truncated" for a in diagnostics["objects"][0]["attempts"])


@pytest.mark.parametrize("response,reason", [
    (candidate("formula", 1, layout_id="foreign SECRET_ID"), "layout_id_mismatch"),
    (candidate("formula", 1, type="figure"), "object_type_mismatch"),
    (RuntimeError("SECRET_API_KEY https://private.example"), "RuntimeError"),
])
def test_identity_errors_and_provider_exceptions_are_isolated_not_blindly_retried(monkeypatch, response, reason):
    outcome, client, _, (_, count, diag) = recover(monkeypatch, [response, candidate("figure", 2)],
                                                 kinds=("formula", "figure"))
    assert count == 2
    assert len(client.calls) == 2
    assert diag["objects"][0]["attempts"][0]["reason"] == reason
    assert outcome["layout"][1]["status"] == "EXTRACTED"
    assert "SECRET" not in json.dumps(diag)
    assert "private.example" not in json.dumps(diag)


@pytest.mark.parametrize("limit,enabled", [(0, True), (1, True), (8, False)])
def test_fanout_and_unavailable_provider_preserve_failed_ledger(monkeypatch, limit, enabled):
    outcome, client, crops, (_, count, diag) = recover(monkeypatch, [candidate()],
        kinds=("table", "formula", "figure"), max_objects=limit, enabled=enabled)
    assert count == (1 if limit == 1 and enabled else 0)
    assert len(client.calls) == count
    assert sum(b["status"] == "FAILED" for b in outcome["layout"]) == 3 - count
    assert all(b["review_required"] for b in outcome["layout"] if b["status"] == "FAILED")
    if not enabled:
        assert crops == []
        assert all(d["reason"] == "provider_unavailable" for d in diag["objects"])


def test_taskmanager_persists_redacted_attempt_diagnostics(monkeypatch, tmp_path):
    outcome, _, _, (_, _, diagnostics) = recover(monkeypatch, [candidate(markdown=PARTIAL), candidate()])
    source = tmp_path / "fixture.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((20, 20), "Mock-only upload fixture")
        pdf.save(str(source))
    manager = fixtures.TaskManager(str(tmp_path / "output"))
    task = manager.start_task("object-recovery-fixture", file_path=str(source))
    result = {"layout": outcome["layout"], "layout_recovery": diagnostics,
              "elements": outcome["payloads"], "rag": {"elements": outcome["payloads"]}}
    manager.update_page_result(task.task_id, 1, result)
    saved = json.loads((tmp_path / "output" / "tasks" / task.task_id / "page_1.json").read_text())
    assert saved["layout_recovery"] == diagnostics
    assert saved["rag"]["elements"]["tables"][0]["layout_id"] == "p1-o001-table"
    assert "SECRET" not in json.dumps(saved)


@pytest.mark.parametrize("initial,info,reason", [
    ({}, {"json_status": "invalid"}, "table_content_empty"),
    ({}, {"json_status": "empty"}, "table_content_empty"),
    ({}, {"json_status": "object"}, "table_content_empty"),
    ({}, {"json_status": "non_object"}, "table_content_empty"),
])
def test_malformed_or_missing_object_retries_and_preserves_each_attempt(monkeypatch, initial, info, reason):
    outcome, client, _, (_, count, diag) = recover(monkeypatch, [(initial, info), candidate()])
    assert count == 2
    assert outcome["layout"][0]["status"] == "EXTRACTED"
    assert diag["objects"][0]["attempts"][0]["reason"] == reason
    assert diag["objects"][0]["attempts"][1]["reason"] == "validated_object"


def test_unmatched_target_diagnostic_survives_later_success(monkeypatch):
    outcome, _, _, _ = recover(monkeypatch, [candidate("formula", 1, layout_id="SECRET_FOREIGN_ID"), candidate("figure", 2)],
                               kinds=("formula", "figure"))
    assert outcome["unmatched_recovery_refs"] == ["p1-o001-formula:layout_id_mismatch"]
    reconciliation = ledger.reconcile_layout("EXTRACTED", outcome["layout"], outcome["payloads"],
                                              outcome["unmatched_recovery_refs"])
    assert reconciliation["complete"] is False
    assert reconciliation["review_required_layout_ids"] == ["p1-o001-formula"]


def test_provider_content_filter_cannot_be_promoted_or_blindly_retried(monkeypatch):
    outcome, _, _, (_, count, diag) = recover(monkeypatch, [(candidate(), {"finish_reason": "content_filter"})])
    assert count == 1
    assert outcome["payloads"]["tables"] == []
    assert diag["objects"][0]["attempts"][0]["reason"] == "provider_content_blocked"


def test_extra_provider_fields_and_coordinates_do_not_escape_into_success_arrays(monkeypatch):
    outcome, _, _, _ = recover(monkeypatch, [candidate(api_key="SECRET", raw="SECRET_RAW", bbox=[0, 0, 1, 1])])
    payload = outcome["payloads"]["tables"][0]
    assert "SECRET" not in json.dumps(payload)
    assert payload["bbox"] == [0.1, 0.2, 0.9, 0.8]


@pytest.mark.parametrize("crop_succeeds,ocr_recovers", [(True, False), (False, False), (True, True)])
def test_real_local_upload_crop_and_client_parser_with_mocked_wire(monkeypatch, tmp_path, crop_succeeds, ocr_recovers):
    from tests import test_pdf2md_enhanced_single_page_tools as protocol_fixtures

    server = protocol_fixtures.server
    source = tmp_path / "mixed-object-fixture.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=300, height=400)
        page.insert_text((20, 20), "Mixed object upload fixture")
        pdf.save(str(source))
    manager = server.TaskManager(str(tmp_path / "output"))
    monkeypatch.setattr(server, "manager", manager)
    monkeypatch.setattr(server, "process_page", processor.process_page)
    raw = fixtures._layout_raw([
        {"index": 1, "label": "table", "bbox_2d": [10, 10, 90, 30], "content": TABLE},
        {"index": 2, "label": "table", "bbox_2d": [10, 35, 90, 60], "content": PARTIAL},
        {"index": 3, "label": "formula", "bbox_2d": [10, 65, 45, 80], "content": ""},
        {"index": 4, "label": "image", "bbox_2d": [50, 65, 90, 90], "content": ""},
    ], markdown="Fixture page text")
    ocr_calls = []

    def ocr_wire(self, path, **kwargs):
        image = fitz.Pixmap(path)
        ocr_calls.append((path, image.width, image.height))
        if "layout-recovery-" not in path:
            return raw
        content = TABLE if ocr_recovers else PARTIAL
        return {"md_results": content, "layout_details": [[{"label": "table", "content": content}]]}

    monkeypatch.setattr(OCRClient, "_call_layout_parsing_raw", ocr_wire)
    monkeypatch.setattr(processor, "OpenAICompatibleOcrClient", OCRClient)
    monkeypatch.setattr(processor, "DynamicVLMClient", VLMClient)
    responses = iter(([] if ocr_recovers else [
        candidate(number=2, markdown=PARTIAL),
        candidate(number=2, markdown=TABLE if crop_succeeds else PARTIAL),
    ]) + [
        candidate("formula", 3), candidate("figure", 4),
    ])
    wire_calls = []

    def wire(self, **kwargs):
        message = kwargs["messages"][0]["content"]
        image = fitz.Pixmap(base64.b64decode(message[1]["image_url"]["url"].split(",", 1)[1]))
        wire_calls.append({"budget": kwargs["max_tokens"], "size": [image.width, image.height],
                           "prompt": message[0]["text"]})
        response = next(responses)
        if "Return ONLY one complete valid HTML" in message[0]["text"]:
            return response.get("markdown", ""), "stream", "stop"
        return json.dumps(response), "stream", "stop"

    monkeypatch.setattr(VLMClient, "_chat_completion_with_stream_fallback", wire)
    start = getattr(server.start_task, "fn", server.start_task)
    process = getattr(server.process_task_page, "fn", server.process_task_page)
    started = json.loads(asyncio.run(start(task_name="object-crop-local-e2e", file_path=str(source))))
    result = json.loads(asyncio.run(process(
        task_id=started["task_id"], page_no=1, policy="force_direct",
        vlm_config={"provider": "fixture", "model": "fixture-vlm", "api_key": "unused-local-only",
                    "base_url": "http://127.0.0.1:1/v1", "max_tokens": 12000, "max_retries": 0},
        routing_config={"render_dpi": 300, "render_cleanup_with_llm": False,
                        "ocr_config": {"glm_ocr": {"enabled": True, "model": "glm-ocr",
                                                   "base_url": "http://127.0.0.1:1"}}},
    )))["page_result"]
    assert len(ocr_calls) == (2 if ocr_recovers else 3)
    assert len(wire_calls) == (2 if ocr_recovers else 4)
    assert all(call["budget"] == 12000 for call in wire_calls)
    assert all(w < 625 and h < 834 for w, h in (call["size"] for call in wire_calls))
    assert ocr_calls[0][1:] == (1250, 1667)
    assert ocr_calls[1][1] < 625 and ocr_calls[1][2] < 834  # actual 150 DPI crop
    if not ocr_recovers:
        assert ocr_calls[2][1] < ocr_calls[1][1] and ocr_calls[2][2] < ocr_calls[1][2]
    assert all("SECRET_ORIGINAL_FRAGMENT" not in call["prompt"] for call in wire_calls)
    assert result["elements"] == result["rag"]["elements"]
    assert len(result["elements"]["tables"]) == (2 if crop_succeeds else 1)
    assert len(result["elements"]["formulas"]) == len(result["elements"]["figures"]) == 1
    assert result["reconciliation"]["complete"] is crop_succeeds
    assert result["reconciliation"]["accounted_for"] is True
    assert [item["reading_order"] for item in result["layout"]] == [1, 2, 3, 4]
    assert result["layout"][1]["bbox"] == [0.1, 0.35, 0.9, 0.6]
    saved = json.loads((tmp_path / "output" / "tasks" / started["task_id"] / "page_1.json").read_text())
    assert saved["layout_recovery"] == result["layout_recovery"]
    assert "SECRET" not in json.dumps(saved["layout_recovery"])
    attempts = saved["layout_recovery"]["objects"][0]["attempts"]
    assert attempts[0]["provider"] == "glm_ocr"
    assert attempts[0]["reason"] == ("validated_object" if ocr_recovers else "table_html_unclosed")
    if not ocr_recovers:
        assert attempts[2]["provider"] == "vlm_ocr"
        assert attempts[2]["finish_reason"] == "stop"
    finalized = manager.finalize_task(started["task_id"], merge_mode="both")
    assert finalized["merged_rag"][0]["rag"]["elements"] == result["elements"]
