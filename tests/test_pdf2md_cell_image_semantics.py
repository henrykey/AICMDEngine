"""Explicit cell semantics survive geometry failure and task result projection."""
import asyncio
import base64
import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from tests.test_pdf2md_cell_image_recovery import (
    sp, pp, GeometryClient, table_target, geometry, source_image,
    LayoutLedgerGLMOcrClient, LayoutLedgerVLMClient, _layout_raw,
)


def semantic_cell(row=0, col=0, **changes):
    return {"row": row, "col": col, "rowspan": 1, "colspan": 1,
            "contains_image": True, "description": "A rectangular component joins the curved outer wall.",
            "status": "complete", **changes}


def candidate(block, cells=None, **changes):
    return {"layout_id": block["layout_id"], "type": "table", "complete": False,
            "cell_image_semantics": {"status": "complete", "cells": cells or [semantic_cell()]}, **changes}


def run(source_image, tmp_path, response=None, table=None, finish="stop", enabled=True):
    target = copy.deepcopy(table or table_target())
    class Client(GeometryClient):
        description_language = "en"
        def extract_object_structured(self, path, block, compact=False):
            self.calls.append(block)
            self.last_object_call_info = {"json_status": "object", "finish_reason": finish}
            return response if response is not None else candidate(block)
    client = Client()
    counts = pp._recover_missing_table_images(source_image, tmp_path, {"tables": [target], "figures": []},
        client, enabled, 1, provider_plan=["vlm_ocr", "vlm_ocr"], max_model_calls=2, describe_cell_images=True)
    return target, client, counts


def test_semantics_survive_unknown_geometry_and_keep_source(source_image, tmp_path):
    table, client, counts = run(source_image, tmp_path)
    assert counts[:2] == (0, 1)
    assert len(client.calls) == 1
    assert table["markdown"] == table_target()["markdown"]
    assert table["cell_image_semantics"]["status"] == "complete"
    assert table["cell_image_semantics"]["cells"][0]["description"]
    assert table["image_unresolved"]
    assert table["manualReviewRequired"]


@pytest.mark.parametrize("change", [{"source_cells": []}, {"contains_images": True, "source_cells": [{"row": 0, "col": 0}]}])
def test_geometry_rejection_does_not_discard_semantics(source_image, tmp_path, change):
    response = candidate(table_target(), complete=True, status="EXTRACTED", **change)
    table, _, _ = run(source_image, tmp_path, response)
    assert table["cell_image_semantics"]["status"] == "complete"
    assert table["image_unresolved"]


def test_valid_geometry_and_existing_assets_are_preserved(source_image, tmp_path):
    table = table_target()
    pp._recover_missing_table_images(source_image, tmp_path, {"tables": [table], "figures": []},
        GeometryClient(), True, 1, provider_plan=["vlm_ocr"], max_model_calls=1)
    assert table["cell_image_inspection_status"] == "complete"
    payload = {"tables": [table], "figures": []}
    pp._attach_figure_assets(source_image, payload, 1)
    old_cells = copy.deepcopy(table["source_cells"])
    table, client, _ = run(source_image, tmp_path, candidate(table), table)
    assert len(client.calls) == 1  # Geometry already complete still permits explicit semantics.
    assert table["source_cells"] == old_cells
    assert payload["figures"][0]["image_asset"]["status"] == "available"


@pytest.mark.parametrize("finish,cell,status", [
    ("length", semantic_cell(), "partial"),
    ("stop", semantic_cell(contains_image=None, status="unresolved"), "partial"),
    ("stop", semantic_cell(description=""), "partial"),
    ("stop", semantic_cell(contains_image=False, description="must be cleared"), "complete"),
])
def test_uncertainty_truncation_and_empty_no_image(source_image, tmp_path, finish, cell, status):
    table, _, _ = run(source_image, tmp_path, candidate(table_target(), [cell]), finish=finish)
    semantics = table["cell_image_semantics"]
    assert semantics["status"] == status
    if cell["contains_image"] is False:
        assert semantics["cells"][0]["description"] == ""
    if finish == "length":
        assert semantics["cells"][0]["description"]
        assert any(i["reason"] == "provider_output_truncated" for i in semantics["issues"])


def test_provider_unavailable_keeps_prior_prose_without_claiming_completion(source_image, tmp_path):
    prior = table_target()
    prior["cell_image_semantics"] = {"status": "complete", "cells": [semantic_cell()], "issues": []}
    table, client, counts = run(source_image, tmp_path, table=prior, enabled=False)
    assert counts[:2] == (0, 0)
    assert not client.calls
    assert table["cell_image_semantics"]["status"] == "not_attempted"
    assert table["cell_image_semantics"]["cells"] == prior["cell_image_semantics"]["cells"]


def test_invalid_response_keeps_prior_prose(source_image, tmp_path):
    prior = table_target()
    prior["cell_image_semantics"] = {"status": "complete", "cells": [semantic_cell()], "issues": []}
    table, _, _ = run(source_image, tmp_path, {}, prior)
    assert table["cell_image_semantics"]["status"] == "failed"
    assert table["cell_image_semantics"]["cells"][0]["description"] == semantic_cell()["description"]


@pytest.mark.parametrize("missing_bbox", [False, True])
@pytest.mark.parametrize("source_field", ["markdown", "render_html", "raw_html"])
def test_single_table_tool_preserves_independent_semantics(source_image, tmp_path, monkeypatch, missing_bbox, source_field):
    class Client(GeometryClient):
        description_language = "en"
        def __init__(self, config):
            super().__init__()
        def extract_object_structured(self, path, block, compact=False):
            self.last_object_call_info = {"json_status": "object", "finish_reason": "stop"}
            response = candidate(block)
            response["cell_image_semantics"]["target_identified"] = True
            return response
    monkeypatch.setattr(sp, "DynamicVLMClient", Client)
    target = {"provider": "vlm_ocr", "page_no": 1, "source_sha1": hashlib.sha1(source_image.read_bytes()).hexdigest(),
              "table": table_target(), "describe_cell_images": True}
    target["table"][source_field] = target["table"].pop("markdown")
    if missing_bbox:
        target["table"].pop("bbox")
    output = json.loads(sp.extract_page_tables_direct(file_path=str(source_image), input_type="image",
        description_language="en", context={"table_image_target": target}))
    assert output["tables"][0]["cell_image_semantics"]["status"] == "complete"
    assert output["model_calls"] == {"glm_ocr": 0, "vlm_ocr": 1}
    assert not output["semantic_status"]["complete"]  # Geometry still incomplete.


def test_recorded_21_image_cells_are_mapped_by_source_grid():
    sample = json.loads((Path(__file__).parent / "fixtures/cell_image_semantics/gb16749_page10.json").read_text())
    origins = sp._normalize_table_contract(sample["table_html"], "structured_json")["source_cells"]
    columns = {"通常设计": 1, "波根加强 A": 2, "套箍 B": 3, "辅助套箍 C(单个)": 4, "辅助套箍 D(两个)": 5}
    # Fixture data rows 1..5 follow three header rows; they are NOT MCP indices.
    descriptions = {(i["row"] + 2, columns[i["column"]]): i["description"] for i in sample["images"]}
    cells = [semantic_cell(c["row"], c["col"], rowspan=c["rowspan"], colspan=c["colspan"],
        contains_image=(c["row"], c["col"]) in descriptions,
        description=descriptions.get((c["row"], c["col"]), "")) for c in origins]
    block = {"layout_id": "page10-table", "source_cell_origins": origins}
    output = pp._cell_image_semantics(block, candidate(block, cells), {"finish_reason": "stop"}, "zh")
    assert output["status"] == "complete"
    assert sum(c["contains_image"] is True for c in output["cells"]) == 21
    assert all(c["description"] == "" for c in output["cells"] if c["contains_image"] is False)
    assert any(c["rowspan"] == 3 and c["row"] == 0 for c in output["cells"])


@pytest.mark.parametrize("force_page_input", [False, True])
def test_process_task_page_two_phase_returns_and_saves_semantics(tmp_path, monkeypatch, force_page_input):
    server = importlib.import_module(sp.__package__ + ".server")
    TaskManager = importlib.import_module(sp.__package__ + ".task_manager").TaskManager
    manager = TaskManager(str(tmp_path / "tasks"))
    monkeypatch.setattr(server, "manager", manager)
    path = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(path)
    task = manager.start_task("fixture", file_data=base64.b64encode(path.read_bytes()).decode())
    source = table_target()["markdown"]
    calls = []
    class OCR(LayoutLedgerGLMOcrClient):
        raw = _layout_raw([{"label": "table", "bbox_2d": [10, 10, 90, 90], "content": source}], source)
    class VLM(LayoutLedgerVLMClient):
        description_language = "en"
        def extract_object_structured(self, path, block, compact=False):
            calls.append(block)
            self.last_object_call_info = {"finish_reason": "stop", "json_status": "object"}
            response = candidate(block) if len(calls) == 1 else {}
            if response:
                response["cell_image_semantics"]["target_identified"] = True
            return response
    monkeypatch.setattr(pp, "OpenAICompatibleOcrClient", OCR)
    monkeypatch.setattr(pp, "DynamicVLMClient", VLM)
    config = {"source_page_no": 10, "ocr_config": {"glm_ocr": {"enabled": True}}}
    first = json.loads(asyncio.run(server.process_task_page(task.task_id, 1, vlm_config={"provider": "fixture"},
        routing_config={**config, "docs_recovery_phase": "recognize"})))
    assert "error" not in first
    table_id = first["page_result"]["elements"]["tables"][0]["layout_id"]
    assert not calls
    if force_page_input:
        def cannot_crop(*args, **kwargs):
            raise ValueError("unreliable_table_crop")
        monkeypatch.setattr(pp, "_crop_layout_block_image", cannot_crop)
    selection = {"table_images": [table_id], "describe_cell_images": True,
                 "image_provider_plan": ["vlm_ocr"], "image_model_budget": 1}
    second = json.loads(asyncio.run(server.process_task_page(task.task_id, 1, vlm_config={"provider": "fixture"},
        routing_config={**config, "docs_recovery_phase": "recover", "docs_recovery_selection": selection})))
    assert "error" not in second
    assert len(calls) == 1
    assert calls[0]["semantic_input_scope"] == ("source_page" if force_page_input else "table_crop")
    result = second["page_result"]
    assert result["cell_image_recovery"]["operation"] == "cell_image_semantics"
    for elements in (result["elements"], result["rag"]["elements"]):
        assert elements["tables"][0]["cell_image_semantics"]["status"] == "complete"
        assert elements["tables"][0]["markdown"] == source
    saved = manager.get_task(task.task_id).pages[1].result
    assert saved["_docs_raw_layout"]["_docs_layout_snapshot"]["payloads"]["tables"][0]["cell_image_semantics"]["cells"]
    third = json.loads(asyncio.run(server.process_task_page(task.task_id, 1, vlm_config={"provider": "fixture"},
        routing_config={**config, "docs_recovery_phase": "recover", "docs_recovery_selection": selection})))
    assert len(calls) == 2
    retried = third["page_result"]["elements"]["tables"][0]["cell_image_semantics"]
    assert retried["status"] == "failed"
    assert retried["cells"][0]["description"] == semantic_cell()["description"]



@pytest.mark.parametrize("fault", ["missing_cell", "duplicate_cell", "wrong_span", "foreign_origin"])
def test_bad_coverage_cannot_be_complete(fault):
    block = {"layout_id": "table", "source_cell_origins": [semantic_cell(), semantic_cell(0, 1)]}
    cells = [semantic_cell(), semantic_cell(0, 1)]
    if fault == "missing_cell":
        cells.pop()
    elif fault == "duplicate_cell":
        cells.append(semantic_cell())
    elif fault == "wrong_span":
        cells[0]["rowspan"] = 2
    else:
        cells[0]["row"] = 100
    output = pp._cell_image_semantics(block, candidate(block, cells), {}, "en")
    assert output["status"] == "partial"
    assert output["issues"]


def test_table_crop_failure_uses_source_page_before_sole_request(source_image, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("crop_failed")
    monkeypatch.setattr(pp, "_crop_layout_block_image", fail)
    response = candidate(table_target())
    response["cell_image_semantics"]["target_identified"] = True
    table, client, counts = run(source_image, tmp_path, response)
    assert counts[:2] == (0, 1)
    assert client.calls[0]["semantic_input_scope"] == "source_page"
    assert table["cell_image_semantics"]["status"] == "complete"


def test_semantics_do_not_execute_or_replace_geometry(source_image, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A semantic operation must not validate cell geometry")
    monkeypatch.setattr(pp, "_validate_cell_image_recovery", forbidden)
    response = {**geometry(table_target()), "cell_image_semantics": {"status": "complete", "cells": [semantic_cell()]}}
    table, _, _ = run(source_image, tmp_path, response)
    assert table["cell_image_semantics"]["status"] == "complete"
    assert table["image_unresolved"] == table_target()["image_unresolved"]
    assert "source_cells" not in table


def test_prompt_requests_independent_semantics_with_language(monkeypatch):
    client = sp.DynamicVLMClient(None)
    client.description_language = "zh"
    captured = {}
    def respond(path, prompt, **kwargs):
        captured.update(prompt=prompt, **kwargs)
        client.last_call_info = {"finish_reason": "stop"}
        return json.dumps(candidate({"layout_id": "table"}))
    monkeypatch.setattr(client, "_call_image_prompt", respond)
    client.extract_object_structured("unused", {"layout_id": "table", "type": "table",
        "recovery_target": "cell_image_semantics"})
    assert "cell_image_semantics" in captured["prompt"]
    assert "INDEPENDENT" in captured["prompt"]
    assert "no_image_cells" in captured["prompt"]
    assert "bbox_space" not in captured["prompt"]
    assert "Do NOT return geometry" in captured["prompt"]
    assert "Chinese" in captured["prompt"]
    assert captured["safe_errors"] is True


@pytest.mark.parametrize("physical_limit", [0, 1])
def test_semantic_request_cannot_fallback_to_second_physical_request(source_image, physical_limit):
    client = sp.DynamicVLMClient({"table_analysis_max_physical_requests": physical_limit})
    client.enabled = True
    sends = []
    def create(**kwargs):
        client._count_physical_request(None)
        sends.append(kwargs)
        raise OSError("transport failure")
    client._client = SimpleNamespace(max_retries=2, chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(Exception):
        client.extract_object_structured(str(source_image), {"layout_id": "table", "type": "table",
            "recovery_target": "cell_image_semantics"})
    assert len(sends) == physical_limit
    assert client.physical_requests == physical_limit
    assert client._client.max_retries == 2


def test_invalid_explicit_target_cannot_claim_inspection_complete(source_image, tmp_path):
    ctx = sp.SinglePageContext(source_path=source_image, image_path=source_image, input_type="image", page_no=1, page_text="")
    output = sp._recover_single_table_image("extract_page_tables", ctx,
        {"provider": "vlm_ocr", "describe_cell_images": True, "table": {}}, "en", {}, {}, tmp_path)
    assert not output["semantic_status"]["complete"]
    assert output["model_calls"] == {"glm_ocr": 0, "vlm_ocr": 0}


def test_zero_caller_budget_reports_not_attempted(source_image, tmp_path):
    table = table_target()
    client = GeometryClient()
    counts = pp._recover_missing_table_images(source_image, tmp_path, {"tables": [table], "figures": []},
        client, True, 1, provider_plan=["vlm_ocr"], max_model_calls=0, describe_cell_images=True)
    assert counts[:2] == (0, 0)
    assert table["cell_image_semantics"]["status"] == "not_attempted"
    assert table["cell_image_semantics"]["issues"] == [{"reason": "model_budget_exhausted"}]


@pytest.mark.parametrize("geometry_state", ["missing", "unreliable"])
def test_semantics_can_use_source_page_without_reliable_table_bbox(source_image, tmp_path, geometry_state):
    table = table_target()
    if geometry_state == "missing":
        table.pop("bbox")
    else:
        table["bbox_space"] = "unknown"
    response = candidate(table)
    response["cell_image_semantics"]["target_identified"] = True
    result, client, counts = run(source_image, tmp_path, response, table)
    assert counts[:2] == (0, 1)
    assert client.calls[0]["semantic_input_scope"] == "source_page"
    assert result["cell_image_semantics"]["status"] == "complete"
    assert result["markdown"] == table["markdown"]


def test_later_no_image_cannot_clear_previous_image_description(source_image, tmp_path):
    prior = table_target()
    prior["cell_image_semantics"] = {"status": "complete", "cells": [semantic_cell()], "issues": []}
    result, _, _ = run(source_image, tmp_path, candidate(prior, [semantic_cell(contains_image=False, description="")]), prior)
    semantics = result["cell_image_semantics"]
    assert semantics["status"] == "partial"
    assert semantics["cells"][0]["contains_image"] is True
    assert semantics["cells"][0]["description"] == semantic_cell()["description"]
    assert semantics["cells"][0]["status"] == "unresolved"
    assert any(i["reason"] == "semantic_image_presence_conflict" for i in semantics["issues"])


def test_successful_geometry_cannot_hide_semantic_failure(source_image, tmp_path):
    result, _, (_, _, diagnostics) = run(source_image, tmp_path, geometry(table_target()))
    assert result["cell_image_semantics"]["status"] == "failed"
    assert diagnostics["objects"][0]["outcome"] == "failed"


def test_compact_no_image_evidence_expands_to_existing_sidecar_contract():
    block = {"layout_id": "table", "source_cell_origins": [semantic_cell(), semantic_cell(0, 1, rowspan=2)]}
    response = candidate(block)
    response["cell_image_semantics"] = {"status": "complete", "cells": [{"row": 0, "col": 0,
        "contains_image": True, "description": semantic_cell()["description"], "status": "complete"}],
        "no_image_cells": [[0, 1]]}
    output = pp._cell_image_semantics(block, response, {}, "en")
    assert output["status"] == "complete"
    assert output["cells"][1] == semantic_cell(0, 1, rowspan=2, contains_image=False, description="")


@pytest.mark.parametrize("identified", [False, None])
def test_full_page_requires_identification_of_selected_table(source_image, tmp_path, identified):
    table = table_target()
    table.pop("bbox")
    response = candidate(table)
    response["cell_image_semantics"]["target_identified"] = identified
    result, client, counts = run(source_image, tmp_path, response, table)
    assert counts[:2] == (0, 1)
    assert result["cell_image_semantics"]["status"] == "failed"
    assert result["cell_image_semantics"]["cells"] == []
    assert result["cell_image_semantics"]["issues"] == [{"reason": "semantic_target_unverified"}]


@pytest.mark.parametrize("new_cell", [semantic_cell(description=""), semantic_cell(description="Uncertain new content.", status="unresolved"), semantic_cell(contains_image=None, description="")])
def test_partial_retry_keeps_existing_valid_prose(source_image, tmp_path, new_cell):
    prior = table_target()
    prior["cell_image_semantics"] = {"status": "complete", "cells": [semantic_cell()], "issues": []}
    result, _, _ = run(source_image, tmp_path, candidate(prior, [new_cell]), prior)
    semantics = result["cell_image_semantics"]
    assert semantics["status"] == "partial"
    assert semantics["cells"][0]["description"] == semantic_cell()["description"]
    assert semantics["cells"][0]["contains_image"] is True
    assert semantics["cells"][0]["status"] == "unresolved"


@pytest.mark.parametrize("field", ["render_html", "raw_html", "sourceHtml", "html"])
def test_existing_html_sources_preserve_origins(source_image, tmp_path, field):
    target = table_target()
    markup = target.pop("markdown")
    target[field] = markup
    table, client, counts = run(source_image, tmp_path, table=target)
    assert counts[:2] == (0, 1)
    assert table["cell_image_semantics"]["status"] == "complete"
    assert "markdown" not in table
    assert client.calls[0]["markdown"] == markup
    assert counts[2]["objects"][0]["source_field"] == field


@pytest.mark.parametrize("source", [
    {"rows": [["[image]"]]},
    {"columns": ["header"], "normalized_rows": [["[image]"]]},
    {"render_html": "<table><tr><td>broken"},
    {"render_html": "<table><tr><td rowspan='3'>x</td></tr></table>"},
    {"render_html": "<table><tr><td>a</td></tr></table><table><tr><td>b</td></tr></table>"},
])
def test_unreliable_source_does_not_guess_or_call_provider(source_image, tmp_path, source):
    target = table_target()
    target.pop("markdown")
    target.update(source)
    target["cell_image_semantics"] = {"cells": [semantic_cell()]}
    table, client, counts = run(source_image, tmp_path, table=target)
    assert counts[:2] == (0, 0)
    assert not client.calls
    assert table["cell_image_semantics"]["status"] == "not_attempted"
    assert table["cell_image_semantics"]["cells"] == [semantic_cell()]
    assert counts[2]["objects"][0]["reason"] == "table_structure_unavailable"


def test_full_page_other_table_identity_is_rejected(source_image, tmp_path):
    target = table_target()
    target.pop("bbox")
    response = candidate({"layout_id": "another-table"})
    response["cell_image_semantics"]["target_identified"] = True
    table, client, _ = run(source_image, tmp_path, table=target, response=response)
    assert client.calls[0]["semantic_input_scope"] == "source_page"
    assert table["cell_image_semantics"]["status"] == "failed"
    assert table["cell_image_semantics"]["cells"] == []
    assert table["cell_image_semantics"]["issues"][0]["reason"] == "semantic_response_identity_invalid"


@pytest.mark.parametrize("field", ["markdown", "render_html", "raw_html"])
@pytest.mark.parametrize("has_image", [True, False])
def test_html_semantics_then_geometry_and_assets(source_image, tmp_path, monkeypatch, field, has_image):
    target = table_target()
    markup = '<table><tr><td colspan="2">Original drawing</td></tr></table>'
    target.pop("markdown")
    target[field] = markup
    response = candidate(target, [semantic_cell(colspan=2, contains_image=has_image,
                         description="A rectangular component." if has_image else "")])
    table, _, _ = run(source_image, tmp_path, table=target, response=response)
    semantics = copy.deepcopy(table["cell_image_semantics"])
    assert semantics["status"] == "complete"
    class Client(GeometryClient):
        def __init__(self, config):
            super().__init__()
        def extract_object_structured(self, path, block, compact=False):
            assert block["markdown"] == markup
            assert block["source_cell_origins"][0]["colspan"] == 2
            out = geometry(block)
            out["source_cells"][0]["colspan"] = 2
            if not has_image:
                out.update(contains_images=False, source_cells=[])
            return out
    monkeypatch.setattr(sp, "DynamicVLMClient", Client)
    output = json.loads(sp.extract_page_tables_direct(file_path=str(source_image), input_type="image",
        description_language="en", context={"table_image_target": {
            "provider": "vlm_ocr", "page_no": 1,
            "source_sha1": hashlib.sha1(source_image.read_bytes()).hexdigest(), "table": table}}))
    recovered = output["tables"][0]
    assert recovered["cell_image_inspection_status"] == "complete"
    assert recovered["cell_image_semantics"] == semantics
    assert recovered[field] == markup
    if field != "markdown":
        assert not recovered.get("markdown")
    assert output["model_calls"] == {"glm_ocr": 0, "vlm_ocr": 1}
    if has_image:
        assert recovered["source_cells"][0]["colspan"] == 2
        assert output["figures"][0]["image_asset"]["status"] == "available"
        assert base64.b64decode(output["figures"][0]["image_asset"]["data"].split(",", 1)[1]).startswith(b"\x89PNG")
    else:
        assert not output["figures"]


@pytest.mark.parametrize("field", ["render_html", "raw_html"])
@pytest.mark.parametrize("bad", ["span", "position", "coordinate_space", "bounds", "source"])
def test_html_geometry_keeps_validation_boundaries(source_image, field, bad):
    target = table_target()
    target[field] = target.pop("markdown")
    response = geometry(target)
    cell = response["source_cells"][0]
    if bad == "span":
        cell["colspan"] = 2
    elif bad == "position":
        cell["row"] = 99
    elif bad == "coordinate_space":
        cell["bbox_space"] = "normalized_page"
    elif bad == "bounds":
        cell["bbox"] = [-1, 0, 2, 1]
    else:
        target[field] += target[field]
    reason, result = pp._validate_cell_image_recovery(target, response,
        {"pixel_bbox": [40, 20, 160, 80]}, source_image)
    assert reason in {"cell_source_mismatch", "invalid_cell_image_geometry", "table_structure_unavailable"}
    assert result is None
