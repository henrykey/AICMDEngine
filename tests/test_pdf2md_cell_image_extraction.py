"""Automatic table image metadata must reach the existing crop pipeline."""
import importlib
import pytest
from tests.test_pdf2md_enhanced_single_page_tools import single_page_tools as sp

pp = importlib.import_module(sp.__package__ + '.page_processor')
vlm_module = importlib.import_module(sp.__package__ + '.vlm_client')


def cell():
    return {'row': 0, 'col': 0, 'text': 'Original', 'rowspan': 1, 'colspan': 1,
            'bbox': [0, 0, 1, 1], 'bbox_space': 'normalized_page',
            'image_regions': [{'image_id': 'a', 'bbox': [.1, .1, .4, .4],
                               'bbox_space': 'normalized_page'}]}


def test_source_geometry_reaches_existing_asset_pipeline(tmp_path):
    import fitz
    path = tmp_path / 'page.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pix.clear_with(255)
    pix.save(str(path))
    table = {'layout_id': 'p7-t', 'bbox': [0, 0, 1, 1], 'bbox_space': 'normalized_page',
             'markdown': '<table><tr><td>Original</td></tr></table>',
             'reading_order': 4, 'source_block_index': 3}
    original = table['markdown']
    table.update(contains_images=True, source_cells=[cell()])
    payloads = {'tables': [table], 'figures': []}
    pp._attach_figure_assets(path, payloads, 7)
    assert len(payloads['figures']) == 1
    assert payloads['figures'][0]['image_asset']['status'] == 'available'
    assert payloads['figures'][0]['image_asset']['page_no'] == 7
    assert payloads['figures'][0]['parent_relation']['cell_source'] == 'r0c0'
    assert payloads['figures'][0]['reading_order'] == 4
    assert payloads['figures'][0]['source_block_index'] == 3
    assert table['markdown'] == original
    output = pp._build_layout_output_elements('', payloads, 'full_glm_ocr')
    assert output['tables'][0]['source_cells'][0]['image_regions'] == cell()['image_regions']


@pytest.mark.parametrize('cells', [[], [{**cell(), 'image_regions': []}]])
def test_detected_but_unlocated_image_is_incomplete(cells):
    data = {'tables': [{'layout_id': 't', 'contains_images': True, 'source_cells': cells}], 'figures': []}
    pp._attach_cell_image_figures(data, 1)
    assert data['tables'][0]['image_unresolved']
    assert data['tables'][0]['manualReviewRequired'] is True
    assert data['figures'] == []


def test_plain_table_has_no_image_failure():
    table = {'layout_id': 't', 'contains_images': False, 'source_cells': []}
    data = {'tables': [table], 'figures': []}
    pp._attach_cell_image_figures(data, 1)
    assert not table.get('image_unresolved')
    assert data['figures'] == []


def test_prompts_request_cell_image_regions(monkeypatch):
    prompts = []
    client = vlm_module.DynamicVLMClient({})
    monkeypatch.setattr(client, '_call_image_prompt', lambda path, prompt, **kw: prompts.append(prompt) or '{}')
    client.extract_region_structured('unused', semantic_objects=[{'object_ref': 'tables:0', 'type': 'table'}])
    prompts.extend([sp._prompt_tables('', True), sp._prompt_table_metadata([], '')])
    assert all('image_regions' in prompt and 'contains_images' in prompt for prompt in prompts)


def test_direct_table_uses_same_crop_pipeline(tmp_path):
    import fitz
    path = tmp_path / 'page.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pix.clear_with(255)
    pix.save(str(path))
    ctx = sp.SinglePageContext(source_path=path, image_path=path, input_type='image', page_no=3, page_text='')
    tables = [{'bbox': [0, 0, 1, 1], 'bbox_space': 'normalized_page', 'source_cells': [cell()]}]
    figures = []
    sp._attach_single_page_figure_assets(ctx, figures, tables)
    assert figures[0]['image_asset']['status'] == 'available'
    assert figures[0]['parent_relation']['table_layout_id'] == tables[0]['layout_id']


def test_visual_merge_preserves_ocr_cell_text():
    original = {**cell(), 'text': '001'}
    table = {'source_cells': [original]}
    pp._merge_table_image_metadata(table, {'source_cells': [cell()]})
    assert table['source_cells'][0]['text'] == '001'


def test_visual_merge_rejects_conflicting_cell_geometry():
    original = {**cell(), 'bbox': [0, 0, .5, 1], 'image_regions': []}
    table = {'source_cells': [original]}
    pp._merge_table_image_metadata(table, {'source_cells': [cell()]})
    assert table['image_unresolved']
    assert original['image_regions'] == []


def test_duplicate_visual_cells_are_not_selected_by_order():
    table = {}
    pp._merge_table_image_metadata(table, {'source_cells': [cell(), cell()]})
    assert table['image_unresolved']
    assert not table['source_cells']


def test_multiple_images_keep_distinct_identity(tmp_path):
    import fitz
    path = tmp_path / 'page.png'
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pix.clear_with(255)
    pix.save(str(path))
    source_cell = cell()
    source_cell['image_regions'].append({'image_id': 'b', 'bbox': [.6, .6, .9, .9], 'bbox_space': 'normalized_page'})
    data = {'tables': [{'layout_id': 't', 'bbox': [0, 0, 1, 1], 'bbox_space': 'normalized_page', 'source_cells': [source_cell]}], 'figures': []}
    pp._attach_figure_assets(path, data, 2)
    assert len({f['layout_id'] for f in data['figures']}) == 2
    assert all(f['image_asset']['status'] == 'available' for f in data['figures'])
    pp._attach_figure_assets(path, data, 2)
    assert len(data['figures']) == 2
