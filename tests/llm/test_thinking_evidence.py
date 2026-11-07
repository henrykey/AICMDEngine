from src.llm.thinking_evidence import find_explicit_family, restore_claim_quotes, restore_quoted_evidence, validate_claims


def claim(dimension="thinking", option="enabled", model="glm-4.6v-flashx", support="supported"):
    quote = f"{model} thinking type {option} is supported"
    return {"dimension": dimension, "option": option, "support": support, "scope": "exact", "series": None,
            "parameters": {"thinking": {"type": option}}, "evidence": {"url": "official", "quote": quote}, "relation_evidence": None}


def test_exact_model_does_not_accept_similar_model():
    item = claim(model="glm-4.6v-flash")
    accepted, conflicts = validate_claims("glm-4.6v-flashx", {"official": item["evidence"]["quote"]}, [item])
    assert accepted == {} and conflicts == []


def test_cross_page_series_requires_model_relation_and_capability_evidence():
    item = claim(model="glm-4.6v")
    item.update(scope="series", series="glm-4.6v", relation_evidence={"url": "relation", "quote": "glm-4.6v series includes glm-4.6v-flashx"})
    sources = {"official": item["evidence"]["quote"], "relation": item["relation_evidence"]["quote"]}
    accepted, _ = validate_claims("glm-4.6v-flashx", sources, [item])
    assert accepted[("thinking", "enabled")][0]["scope"] == "series"
    item["relation_evidence"]["quote"] = "glm-4.6v / glm-4.6v-flash"
    assert validate_claims("glm-4.6v-flashx", sources, [item])[0] == {}


def test_cooccurrence_or_exclusion_is_not_a_family_relation():
    item = claim(model="glm-4.6v")
    item.update(scope="series", series="glm-4.6v")
    for relation in ("glm-4.6v versus glm-4.6v-flashx", "glm-4.6v-flashx is not in glm-4.6v series",
                     "glm-4.6v series is unrelated to glm-4.6v-flashx",
                     "glm-4.6v series includes other models. glm-4.6v-flashx exists"):
        item["relation_evidence"] = {"url": "relation", "quote": relation}
        sources = {"official": item["evidence"]["quote"], "relation": relation}
        assert validate_claims("glm-4.6v-flashx", sources, [item])[0] == {}


def test_explicit_official_group_is_labeled_as_inference():
    item = claim(model="glm-4.6v")
    relation = "GLM-4.6V/GLM-4.6V-Flash/GLM-4.6V-FlashX series"
    item.update(scope="series", series="glm-4.6v", relation_evidence={"url": "relation", "quote": relation})
    accepted, _ = validate_claims("glm-4.6v-flashx", {"official": item["evidence"]["quote"], "relation": relation}, [item])
    assert accepted[("thinking", "enabled")][0]["scope"] == "series"


def test_family_search_requires_explicit_candidate_and_exact_source_relation():
    relation = "GLM-4.6V/GLM-4.6V-Flash/GLM-4.6V-FlashX series"
    assert find_explicit_family("glm-4.6v-flashx", {"official": relation}, None) is None
    assert find_explicit_family("glm-4.6v-flashx", {"official": relation}, "glm-4.6v")["relation_evidence"]["quote"] == relation
    assert find_explicit_family("glm-4.6v-flash", {"official": "GLM-4.6V/GLM-4.6V-FlashX series"}, "glm-4.6v") is None
    assert find_explicit_family("glm-4.6v-flashx", {"official": relation,
        "other": "glm-4.6v-flashx does not belong to glm-4.6v series"}, "glm-4.6v") is None


def test_mixed_model_list_is_not_a_family_relation():
    relation = "GLM-4.6V/GLM-4.6V-Flash/GLM-4.6V-FlashX/GLM-4.1v-thinking series"
    assert find_explicit_family("glm-4.6v-flashx", {"official": relation}, "glm-4.6v") is None


def test_conflicting_sources_are_not_promoted():
    yes = claim()
    no = claim(support="unsupported")
    no["parameters"] = {}
    no["evidence"] = {"url": "other", "quote": "glm-4.6v-flashx thinking enabled is not supported"}
    sources = {"official": yes["evidence"]["quote"], "other": no["evidence"]["quote"]}
    accepted, conflicts = validate_claims("glm-4.6v-flashx", sources, [yes, no])
    assert accepted == {} and conflicts[0]["option"] == "enabled"


def test_effort_levels_are_independent_and_cannot_be_mislabeled():
    item = claim()
    item.update(dimension="reasoning_effort", option="high", parameters={"reasoning_effort": "low"})
    item["evidence"]["quote"] = "glm-4.6v-flashx reasoning_effort high low"
    assert validate_claims("glm-4.6v-flashx", {"official": item["evidence"]["quote"]}, [item])[0] == {}
    item["parameters"] = {"reasoning_effort": "high"}
    accepted, _ = validate_claims("glm-4.6v-flashx", {"official": item["evidence"]["quote"]}, [item])
    assert ("reasoning_effort", "high") in accepted
    assert ("reasoning_effort", "low") not in accepted


def test_effort_combination_requires_enabled_switch_and_explicit_parameter_terms():
    item = claim()
    item.update(dimension="reasoning_effort", option="max",
        parameters={"thinking": {"type": "enabled"}, "reasoning_effort": "max"})
    item["evidence"]["quote"] = "glm-4.6v-flashx thinking type enabled reasoning_effort max"
    sources = {"official": item["evidence"]["quote"]}
    assert ("reasoning_effort", "max") in validate_claims("glm-4.6v-flashx", sources, [item])[0]
    item["parameters"]["thinking"]["type"] = "disabled"
    assert validate_claims("glm-4.6v-flashx", sources, [item])[0] == {}


def test_series_identity_must_not_be_the_model_itself():
    item = claim()
    item.update(scope="series", series="glm-4.6v-flashx",
                relation_evidence={"url": "official", "quote": item["evidence"]["quote"]})
    assert validate_claims("glm-4.6v-flashx", {"official": item["evidence"]["quote"]}, [item])[0] == {}


def test_bad_claim_does_not_discard_good_claim_and_reason_is_bounded():
    good = claim()
    bad = {**good, "scope": []}
    diagnostics = {}
    accepted, _ = validate_claims("glm-4.6v-flashx", {"official": good["evidence"]["quote"]}, [bad, good], diagnostics)
    assert ("thinking", "enabled") in accepted
    assert diagnostics == {"claim_category": 1}


def test_missing_evidence_terms_are_reported_without_quote():
    item = claim()
    for quote, reason in (("other-model thinking type enabled", "evidence_model_missing"),
                          ("glm-4.6v-flashx mode type enabled", "evidence_dimension_missing"),
                          ("glm-4.6v-flashx thinking type other", "evidence_option_missing")):
        item["evidence"]["quote"] = quote
        diagnostics = {}
        validate_claims("glm-4.6v-flashx", {"official": quote}, [item], diagnostics)
        assert diagnostics == {reason: 1}


def test_dotted_thinking_field_is_accepted_without_weakening_model_boundary():
    item = claim()
    item["evidence"]["quote"] = "glm-4.6v-flashx thinking.type enabled supported"
    sources = {"official": item["evidence"]["quote"]}
    assert ("thinking", "enabled") in validate_claims("glm-4.6v-flashx", sources, [item])[0]
    assert validate_claims("glm-4.6v-flash", sources, [item])[0] == {}


def test_unsupported_requires_negative_in_same_option_context():
    item = claim(dimension="reasoning_effort", option="high", support="unsupported")
    item["parameters"] = {}
    quote = "glm-4.6v-flashx thinking disabled is not supported. reasoning_effort high is allowed"
    item["evidence"]["quote"] = quote
    assert validate_claims("glm-4.6v-flashx", {"official": quote}, [item])[0] == {}


def test_ellipsis_recovery_requires_unique_ordered_short_source_span():
    prefix = "glm-5.3-flash thinking.type"
    suffix = "reasoning_effort high"
    document = prefix + " intervening official text " + suffix
    ref = {"url": "official", "quote": prefix + " ... " + suffix}
    repairs = []
    assert restore_quoted_evidence(ref, {"official": document}, repairs)["quote"] == document
    assert repairs[0]["method"] == "unique_ellipsis" and len(repairs[0]["original_sha256"]) == 64
    assert "quote" not in repairs[0]
    assert restore_quoted_evidence(ref, {"official": document + " " + prefix}) == ref
    assert restore_quoted_evidence(ref, {"official": suffix + " " + prefix}) == ref
    assert restore_quoted_evidence(ref, {"official": prefix + "x" * 5001 + suffix}) == ref
    assert restore_quoted_evidence({"url": "official", "quote": "short ... short"}, {"official": document})["quote"] == "short ... short"


def test_model_context_recovery_requires_one_unambiguous_source_sentence():
    item = claim(model="glm-5.3-flash")
    item["evidence"]["quote"] = "thinking type enabled is supported"
    quote = item["evidence"]["quote"]
    document = "glm-5.3-flash " + quote + "."
    repairs = []
    recovered = restore_claim_quotes([item], {"official": document}, repairs, "glm-5.3-flash")
    assert ("thinking", "enabled") in validate_claims("glm-5.3-flash", {"official": document}, recovered)[0]
    assert repairs[0]["method"] == "unique_model_context"
    assert len(repairs[0]["original_sha256"]) == len(repairs[0]["restored_sha256"]) == 64
    for ambiguous in (document + " " + quote, "glm-5.3-flash. " + quote,
                      "glm-5.3-flash and glm-5.3-flashx " + quote,
                      "Unlike gpt-4, glm-5.3-flash " + quote):
        assert restore_claim_quotes([item], {"official": ambiguous}, model="glm-5.3-flash")[0] == item


def test_exact_claim_only_fills_optional_relationship_fields():
    item = claim()
    del item["series"], item["relation_evidence"]
    sources = {"official": item["evidence"]["quote"]}
    restored = restore_claim_quotes([item], sources, model="glm-4.6v-flashx")
    assert restored[0]["series"] is None and restored[0]["relation_evidence"] is None
    assert ("thinking", "enabled") in validate_claims("glm-4.6v-flashx", sources, restored)[0]
    del item["parameters"]
    assert validate_claims("glm-4.6v-flashx", sources, restore_claim_quotes([item], sources))[0] == {}
    item["scope"] = "series"
    assert "series" not in restore_claim_quotes([item], sources)[0]


def test_model_context_recovery_does_not_override_negative_evidence():
    item = claim(model="glm-5.3-flash")
    item["evidence"]["quote"] = "thinking type enabled is not supported"
    document = "glm-5.3-flash " + item["evidence"]["quote"] + "."
    recovered = restore_claim_quotes([item], {"official": document}, model="glm-5.3-flash")
    assert validate_claims("glm-5.3-flash", {"official": document}, recovered)[0] == {}


def test_explicit_group_recovery_and_ambiguous_counterexamples():
    item = claim(model="glm-5.3-flash")
    item.update(dimension="reasoning_effort", option="high", parameters={"reasoning_effort": "high"})
    item["evidence"]["quote"] = "仅支持 max 、 high 、 low"
    quote = item["evidence"]["quote"]
    list_text = "针对 GLM-5.3 GLM-5.3-FLASH GLM-5.3-FLASHX ，" + quote
    document = "reasoning_effort : 可选值 在 API 请求中 " + list_text + "，其余输入将报错；"
    recovered = restore_claim_quotes([item], {"official": document}, model="glm-5.3-flash")
    assert ("reasoning_effort", "high") in validate_claims("glm-5.3-flash", {"official": document}, recovered)[0]
    for group in ("针对 GLM-5.3-FLASH 与 GLM-5.3-FLASHX 比较，" + quote,
                  "针对 GLM-5.3-FLASH 不包括 GLM-5.3-FLASHX ，" + quote,
                  "针对 GLM-5.3-FLASHX GLM-5.3 ，" + quote):
        source = "reasoning_effort : " + group
        assert restore_claim_quotes([item], {"official": source}, model="glm-5.3-flash")[0] == item
    assert restore_claim_quotes([item], {"official": document + quote}, model="glm-5.3-flash")[0] == item


def test_explicit_group_model_directly_followed_by_comma():
    item = claim(model="glm-5.3-flash")
    item.update(dimension="reasoning_effort", option="high", parameters={"reasoning_effort": "high"})
    item["evidence"]["quote"] = "仅支持 max、high、low"
    for comma in ("，", ","):
        document = "reasoning_effort: 在 API 请求中针对 GLM-5.3 GLM-5.3-flash" + comma + item["evidence"]["quote"]
        restored = restore_claim_quotes([item], {"official": document}, model="glm-5.3-flash")
        assert ("reasoning_effort", "high") in validate_claims("glm-5.3-flash", {"official": document}, restored)[0]


def test_rejected_model_group_does_not_fall_back_to_single_model_context():
    item = claim(model="glm-5.3-flash")
    item.update(dimension="reasoning_effort", option="high", parameters={"reasoning_effort": "high"})
    item["evidence"]["quote"] = "仅支持 max、high、low"
    document = "reasoning_effort: 针对 glm-5.3-flash other-2，" + item["evidence"]["quote"]
    restored = restore_claim_quotes([item], {"official": document}, model="glm-5.3-flash")
    assert restored == [item]
    assert validate_claims("glm-5.3-flash", {"official": document}, restored)[0] == {}


def test_group_quote_with_model_recovers_missing_parameter_heading():
    item = claim(model="glm-5.3-flash")
    item.update(dimension="reasoning_effort", option="high", parameters={"reasoning_effort": "high"})
    item["evidence"]["quote"] = "针对 glm-5.3 glm-5.3-flash，仅支持 max、high、low"
    document = "reasoning_effort: 在 API 请求中 " + item["evidence"]["quote"]
    restored = restore_claim_quotes([item], {"official": document}, model="glm-5.3-flash")
    assert ("reasoning_effort", "high") in validate_claims("glm-5.3-flash", {"official": document}, restored)[0]
    for invalid in (document + " " + item["evidence"]["quote"],
                    "reasoning_effort: 不适用；" + item["evidence"]["quote"],
                    "reasoning_effort: 针对 glm-5.3-flash other-2，仅支持 max、high、low"):
        candidate = {**item, "evidence": {"url": "official", "quote": invalid.split(": ", 1)[-1]}}
        assert validate_claims("glm-5.3-flash", {"official": invalid},
                               restore_claim_quotes([candidate], {"official": invalid}, model="glm-5.3-flash"))[0] == {}
