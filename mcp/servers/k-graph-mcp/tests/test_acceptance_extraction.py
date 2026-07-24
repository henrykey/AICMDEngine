import json
from pathlib import Path

from k_graph_mcp.docintel import ScopedPage
from k_graph_mcp.extraction import PageFactExtractor


HASH_A = "sha256:" + "a" * 64


def test_acceptance_corpus_produces_exact_entities_relations_and_gaps() -> None:
  scenarios = load_scenarios()
  results = {}
  for scenario in scenarios:
    expected = scenario["expected"]
    raw = {
      "entities": [
        {
          "ref": f"e{index}",
          "entity_type": entity["type"],
          "original_mention": entity["name"],
          "display_name": entity["name"],
          "aliases": [],
          "evidence_quote": scenario["source_text"],
        }
        for index, entity in enumerate(expected["entities"])
      ],
      "relations": [],
      "gaps": [
        {"code": code, "description": code}
        for code in expected["gaps"]
      ],
    }
    ref_by_name = {
      entity["name"]: f"e{index}"
      for index, entity in enumerate(expected["entities"])
    }
    raw["relations"] = [
      {
        "source_ref": ref_by_name[relation["source"]],
        "relation_type": relation["type"],
        "target_ref": ref_by_name[relation["target"]],
        "evidence_quote": scenario["source_text"],
      }
      for relation in expected["relations"]
    ]
    result = PageFactExtractor(
      client=FixedExtractionClient(raw)
    ).extract(page(scenario))
    results[scenario["id"]] = result

    assert [
      (entity.display_name, entity.entity_type)
      for entity in result.entities
    ] == [
      (entity["name"], entity["type"])
      for entity in expected["entities"]
    ]
    entity_name_by_key = {
      entity.entity_key: entity.display_name for entity in result.entities
    }
    assert [
      (
        entity_name_by_key[relation.source_entity_key],
        relation.relation_type,
        entity_name_by_key[relation.target_entity_key],
      )
      for relation in result.relations
    ] == [
      (
        relation["source"],
        relation["type"],
        relation["target"],
      )
      for relation in expected["relations"]
    ]
    assert [gap.code for gap in result.gaps] == expected["gaps"]

  assert results["unsupported_cooccurrence"].relations == ()
  assert results["ambiguous_parent_relation"].relations == ()
  tenant_a_key = results["overlapping_name_tenant_a"].entities[0].entity_key
  tenant_b_key = results["overlapping_name_tenant_b"].entities[0].entity_key
  assert tenant_a_key != tenant_b_key


class FixedExtractionClient:
  def __init__(self, value):
    self.value = value

  def extract(self, unit, *, repair, previous_error):
    return self.value


def page(scenario) -> ScopedPage:
  return ScopedPage(
    tenant_id=scenario["tenant_id"],
    document_id="doc-1",
    version=1,
    content_hash=HASH_A,
    page_no=1,
    page_text=scenario["source_text"],
    chunks=(),
  )


def load_scenarios():
  fixture = Path(__file__).parent / "fixtures" / "acceptance_corpus.json"
  return json.loads(fixture.read_text(encoding="utf-8"))["scenarios"]
