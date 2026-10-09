"""Source-first extraction contracts: all provider methods are traps."""
import pytest
from tests.test_pdf2md_calculation_sheet import cs







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




@pytest.mark.parametrize('markup,expected', [
    ('<table><tr><td colspan="2">A</td></tr><tr><td>B</td><td>C</td></tr></table>', False),
    ('<table><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>', False),
    ('<table><tr><td>A</td></tr><tr><td>B</td><td>C</td></tr></table>', True),
])
def test_source_layout_quality_uses_occupied_spans_not_model_reliability(markup, expected):
    quality = cs.calculation_transcription_quality(markup, {'status': 'reliable', 'evidence': []})
    assert (quality['status'] == 'misaligned') == expected




def test_source_quality_review_requires_glyph_and_cell_fidelity():
    prompt = cs.classification_prompt(include_items=False)
    assert 'Only after clearly classifying this object as calculation_sheet' in prompt
    assert 'do not perform this calculation-specific formula/glyph review' in prompt
    assert 'Compare every formula and acceptance-check cell' in prompt
    assert 'Never excuse glyph substitutions or missing indices as normalization' in prompt
    assert 'Use uncertain when a glyph cannot be resolved' in prompt
