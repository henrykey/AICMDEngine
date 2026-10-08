"""Recover a visually confirmed table without losing or absorbing unrelated objects."""
import copy
import fitz
import pytest
from tests.test_pdf2md_cell_image_recovery import pp


@pytest.mark.parametrize('mode', ['complete', 'foreign', 'overlap', 'partial', 'failed'])
def test_missing_table_region_is_transactional_and_scoped(tmp_path, mode):
    image = tmp_path / 'page.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
    pix.clear_with(255); pix.save(image)
    layout = [
        {'layout_id': 'caption', 'type': 'text', 'content': 'Table 2.3\nEvaluation rules', 'bbox': [.1,.1,.9,.2]},
        {'layout_id': 'formula', 'type': 'formula', 'content': 'q=a+b', 'bbox': [.1,.2,.9,.4]},
        {'layout_id': 'existing', 'type': 'table', 'content': '<table><tr><td>keep</td></tr></table>', 'bbox': [.1,.7,.9,.9]},
    ]
    for index, block in enumerate(layout):
        block.update(reading_order=index, bbox_space='normalized_page', status='EXTRACTED')
    outcome = {'layout': layout, 'payloads': {'tables': [dict(layout[2], markdown=layout[2]['content'])],
        'formulas': [dict(layout[1], latex='q=a+b')], 'figures': []}, 'markdown': 'Original page text'}
    before = copy.deepcopy(outcome)
    class VLM:
        last_call_info = {}
        def recognize_layout(self, path, table_context=None):
            assert table_context['candidates'][0]['layout_id'] == 'caption'
            return {'missing_tables': [{'caption_layout_id': 'foreign' if mode == 'foreign' else 'caption',
                'bbox': [.1,.1,.9,.9] if mode == 'overlap' else [.1,.1,.9,.5],
                'member_layout_ids': ['caption'] if mode == 'partial' else ['caption','formula']}]}
        def extract_table_html(self, path, block, compact=False):
            if mode == 'failed':
                raise RuntimeError('synthetic failure')
            return '<table><tr><td>$q=a+b$</td></tr></table>'
    pp._recover_unbound_table_regions(image, tmp_path, outcome, VLM(), True, 8, 150)
    if mode == 'complete':
        assert len(outcome['payloads']['tables']) == 2
        assert outcome['payloads']['tables'][0] == before['payloads']['tables'][0]
        assert outcome['payloads']['formulas'] == []
        recovered = next(x for x in outcome['layout'] if x['layout_id'] != 'existing')
        assert recovered['type'] == 'table'
        assert recovered['absorbed_layout_ids'] == ['caption', 'formula']
    else:
        assert outcome['layout'] == before['layout']
        assert outcome['payloads'] == before['payloads']
    assert outcome['markdown'] == before['markdown']
