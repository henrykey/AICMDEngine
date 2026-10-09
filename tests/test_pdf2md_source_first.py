"""Source-first extraction contracts: all provider methods are traps."""
import pytest
from tests.test_pdf2md_calculation_sheet import cs

@pytest.mark.parametrize('content,format', [
    ('## Check\n\nWhen p > 0: $F=pA$.\n\nNote: retain area A.', 'markdown'),
    ('<table><tr><th colspan="2">Check</th></tr><tr><td>p &gt; 0</td><td>$F=pA$</td></tr></table>', 'html'),
])
def test_source_only_reuses_whole_content_without_structuring_or_blocks(content, format):
    class VLM:
        def extract_calculation_sheet(self, *args):
            pytest.fail('optional calculation organization is disabled')
        def transcribe_calculation_blocks(self, *args):
            pytest.fail('whole source has no evidence requiring block recovery')
    item = {'table_kind': 'calculation_sheet', 'semantic_desc': 'Force check and applicability condition.'}
    saved = []
    calls = cs.extract_calculation_items(VLM(), 'unused', item, content, 'tables:0',
        source_store=lambda ref, selected, text: saved.append(text) or {'artifact_id': 'fixture'})
    assert calls == 0
    assert saved == [content]
    assert item['calculation_source']['original_content'] == content
    assert item['calculation_source']['format'] == format
    assert item['content_format'] == format
    assert item['calculation_source']['pipeline']['semantic']['status'] == 'not_requested'
    assert item['calculation_source']['semantic_status'] == 'available'
    assert 'calculation_sheet' not in item
    assert item['lookup_status'] == 'unavailable'


def test_missing_description_keeps_source_but_does_not_claim_semantic_readiness():
    item = {'table_kind': 'calculation_sheet'}
    cs.extract_calculation_items(object(), 'unused', item, '$F=pA$', 'tables:0')
    assert item['calculation_source']['original_content'] == '$F=pA$'
    assert item['calculation_source']['semantic_status'] == 'missing'
    assert 'calculation_sheet' not in item


def test_shared_wire_samples_preserve_source_layout_and_semantic_capabilities():
    import json
    from pathlib import Path
    samples = json.loads((Path(__file__).parent / 'fixtures/source_first_contract.json').read_text())
    for sample in samples['cases']:
        expected = sample['payload']
        if expected['table_kind'] == 'data_table':
            item = dict(expected)
            cs.complete_calculation_batch(object(), 'unused', [(item, '', 'tables:0')], 0)
            assert item == expected
            continue
        source = expected['calculation_source']
        item = {key: expected[key] for key in ('table_kind', 'semantic_desc', 'layout_id')}
        class Provider:
            def extract_calculation_sheet(self, *args):
                pytest.fail('source samples cannot organize JSON implicitly')
        provider = Provider()
        if sample['name'] in ('logical_reordered', 'partial'):
            item['transcription_quality'] = {'status': 'incomplete'}
        if sample['name'] == 'logical_reordered':
            provider.transcribe_calculation_blocks = lambda selected: (source['original_content'],
                {'status': 'complete', 'reason': None, 'logical_calls': 1, 'blocks': []})
        cs.extract_calculation_items(provider, 'unused', item, source['original_content'], 'tables:0')
        for key in ('original_content', 'format', 'content_sha256', 'layout_status', 'quality_status', 'semantic_status'):
            assert item['calculation_source'][key] == source[key], (sample['name'], key)
        assert item['calculation_source']['pipeline']['semantic']['status'] == 'not_requested'
        assert 'calculation_sheet' not in item


def test_classification_block_ids_disambiguate_repeated_formula_without_retyping():
    content = 'Case A\n$F=pA$\nCase B\n$F=pA$'
    ctx = cs.source_context(content, evidence=True)
    blocks = [block for block in ctx['evidence_blocks'] if block['text'] == '$F=pA$']
    assert len(blocks) == 2 and blocks[0]['id'] != blocks[1]['id']
    item = {}
    cs.apply_calculation_sheet(item, {'table_kind': 'calculation_sheet',
        'classification_evidence': [{'block_id': blocks[1]['id'], 'source_sha256': ctx['sha256']}],
        'transcription_quality': {'status': 'reliable', 'evidence': []}}, content)
    classification = item['table_classification']
    assert item['table_kind'] == 'calculation_sheet'
    assert classification['judgment_status'] == 'model_proposed'
    assert classification['evidence_status'] == 'located'
    assert classification['evidence'][0]['source_range'] == blocks[1]['source_range']
    assert item['transcription_quality']['status'] == 'reliable'


@pytest.mark.parametrize('evidence', [['foreign formula'], ['p'],
    [{'block_id': 'missing', 'source_sha256': 'wrong-source'}]])
def test_unlocated_evidence_keeps_judgment_and_readable_source(evidence):
    content = 'p p\n$F=pA$'
    item = {'description': 'Force calculation with pressure and area.'}
    cs.apply_calculation_sheet(item, {'table_kind': 'calculation_sheet',
        'classification_evidence': evidence}, content)
    assert item['table_kind'] == 'data_table'
    assert item['table_classification']['judgment_status'] == 'model_proposed'
    assert item['table_classification']['proposed_kind'] == 'calculation_sheet'
    assert item['table_classification']['evidence_status'] == 'unresolved'
    assert item['table_classification']['status'] == 'evidence_unresolved'
    saved = []
    cs.complete_calculation_batch(object(), 'unused', [(item, content, 'tables:0')], 0,
        source_store=lambda ref, selected, text: saved.append(text) or {'artifact_id': 'fixture'})
    assert saved == []
    assert 'calculation_source' not in item
    assert 'lookup_status' not in item
    assert 'calculation_sheet' not in item


def test_known_block_from_different_source_does_not_validate():
    ctx = cs.source_context('Repeated\n$F=pA$', evidence=True)
    item = {}
    cs.apply_calculation_sheet(item, {'table_kind': 'data_table',
        'classification_evidence': [{'block_id': ctx['evidence_blocks'][0]['id'],
                                    'source_sha256': ctx['sha256']}]}, 'Different\n$F=pA$')
    assert item['table_kind'] == 'data_table'
    assert item['table_classification']['evidence_status'] == 'unresolved'


def test_model_uncertainty_needs_no_quote_repair():
    item = {}
    cs.apply_calculation_sheet(item, {'table_kind': 'uncertain'}, 'p p')
    assert item['table_classification']['judgment_status'] == 'unresolved'
    assert item['table_classification']['status'] == 'unresolved'
    class Provider:
        def classify_table(self, *args):
            pytest.fail('semantic uncertainty is not a formatting retry')
    assert cs.repair_table_classification(Provider(), 'unused', item, 'p p', 'one', 1) == 0


@pytest.mark.parametrize('block_id', [[], {}, None, 'foreign'])
def test_malformed_block_reference_is_reviewable_not_an_exception(block_id):
    ctx = cs.source_context('$F=pA$', evidence=True)
    item = {}
    cs.apply_calculation_sheet(item, {'table_kind': 'calculation_sheet',
        'classification_evidence': [{'block_id': block_id, 'source_sha256': ctx['sha256']}]}, '$F=pA$')
    assert item['table_classification']['evidence_status'] == 'unresolved'


def test_ambiguous_evidence_does_not_trigger_classification_repair():
    content = 'Case A\n$F=pA$\nCase B\n$F=pA$'
    item = {'markdown': content}
    cs.apply_calculation_sheet(item, {'table_kind': 'calculation_sheet',
        'classification_evidence': ['$F=pA$']}, content)
    class Provider:
        def classify_table(self, *args):
            pytest.fail('ambiguous evidence falls back without repair')
    assert cs.repair_table_classification(Provider(), 'image', item, content, 'tables:0', 1) == 0
    assert item['table_kind'] == 'data_table'
    assert item['markdown'] == content
    assert item['table_classification']['reason'] == 'classification_evidence_ambiguous'


def test_failed_response_defaults_without_retry_and_retains_diagnostic():
    item = {}
    cs.classification_failed(item, 'table_classification_response_incomplete', '$F=pA$')
    assert item['table_classification']['status'] == 'response_invalid'
    assert item['table_classification']['judgment_status'] == 'response_invalid'
    class Provider:
        last_call_info = {}
        def classify_table(self, image, target):
            return {'table_kind': 'calculation_sheet', 'classification_evidence': [{
                'block_id': target['evidence_blocks'][0]['id'], 'source_sha256': target['source_sha256']}]}
    assert cs.repair_table_classification(Provider(), 'image', item, '$F=pA$', 'tables:0', 1) == 0
    assert item['table_kind'] == 'data_table'


@pytest.mark.parametrize('repair_outcome', ['failed', 'budget_exhausted'])
def test_missing_kind_keeps_source_without_classification_repair(repair_outcome):
    content = 'Case A: $F=pA$. Condition: pressure above zero.'
    item = {'markdown': content, 'description': 'Force calculation and its applicability condition.'}
    cs.apply_calculation_sheet(item, {}, content)
    class Provider:
        table_analysis_max_model_calls = 2 if repair_outcome == 'failed' else 1
        def classify_table(self, *args):
            pytest.fail('missing kind must not be retried')
    saved = []
    calls = cs.complete_calculation_batch(Provider(), 'image', [(item, content, 'tables:0')], 1,
        source_store=lambda *args: saved.append(args))
    assert saved == []
    assert item['table_kind'] == 'data_table'
    assert item['table_classification']['status'] == 'not_run'
    assert item['table_classification']['reason'] == 'classification_not_run'
    assert item['markdown'] == content
    assert 'calculation_source' not in item
    assert 'lookup_status' not in item
    assert cs.table_content_quality([item])['complete'] is True
    assert calls == 0


@pytest.mark.parametrize('markup,expected', [
    ('<table><tr><td colspan="2">A</td></tr><tr><td>B</td><td>C</td></tr></table>', False),
    ('<table><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>', False),
    ('<table><tr><td>A</td></tr><tr><td>B</td><td>C</td></tr></table>', True),
])
def test_source_layout_quality_uses_occupied_spans_not_model_reliability(markup, expected):
    quality = cs.calculation_transcription_quality(markup, {'status': 'reliable', 'evidence': []})
    assert (quality['status'] == 'misaligned') == expected


def test_inconsistent_source_layout_recovers_even_when_model_reports_reliable():
    content = '<table><tr><td>A</td></tr><tr><td>B</td><td>C</td></tr></table>'
    recovered = 'A\n\nB | C'
    calls = []
    class VLM:
        def transcribe_calculation_blocks(self, item):
            calls.append(item)
            return recovered, {'status': 'complete', 'reason': None, 'logical_calls': 1, 'blocks': []}
    item = {'table_kind': 'calculation_sheet', 'transcription_quality': {'status': 'reliable', 'evidence': []}}
    cs.extract_calculation_items(VLM(), 'unused', item, content, 'tables:0')
    assert len(calls) == 1
    assert item['calculation_source']['original_content'] == recovered
    assert item['calculation_source']['layout_status'] == 'logical_reordered'
    assert item['calculation_source']['transcription_quality']['status'] == 'misaligned'


def test_source_quality_review_requires_glyph_and_cell_fidelity():
    prompt = cs.classification_prompt(include_items=False)
    assert 'Only after clearly classifying this object as calculation_sheet' in prompt
    assert 'do not perform this calculation-specific formula/glyph review' in prompt
    assert 'Compare every formula and acceptance-check cell' in prompt
    assert 'Never excuse glyph substitutions or missing indices as normalization' in prompt
    assert 'Use uncertain when a glyph cannot be resolved' in prompt
