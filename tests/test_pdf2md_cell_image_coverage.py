"""Generic source coverage for complete tables and derived cell figures."""
import copy
import importlib
import pytest
from tests.test_pdf2md_cell_image_extraction import pp, cell
ledger = importlib.import_module(pp.__package__ + '.layout_ledger')


def test_complete_html_still_needs_visual_inventory():
    table = {'layout_id': 't', 'markdown': '<table><tr><td>Dimensions</td></tr></table>',
             'bbox': [0, 0, 1, 1], 'bbox_space': 'normalized_page'}
    assert pp._table_needs_cell_image_inspection(table)
    table['contains_images'] = False
    assert pp._table_needs_cell_image_inspection(table)
    table['cell_image_inspection_status'] = 'complete'
    assert not pp._table_needs_cell_image_inspection(table)


@pytest.mark.parametrize('invalid', [None, 'foreign_parent', 'outside_cell', 'duplicate', 'missing_asset'])
def test_derived_child_requires_unique_valid_source_cell_and_asset(invalid):
    table = {'layout_id': 't', 'bbox': [0, 0, 1, 1], 'bbox_space': 'normalized_page',
             'contains_images': True, 'source_cells': [cell()]}
    payload = {'tables': [table], 'figures': []}
    pp._attach_cell_image_figures(payload, 3)
    figure = payload['figures'][0]
    figure['image_asset'] = {'status': 'available', 'layout_id': figure['layout_id']}
    if invalid == 'foreign_parent': figure['cell_image_source']['table_layout_id'] = 'other'
    if invalid == 'outside_cell': figure['bbox'] = [.7, .7, 1, 1]
    if invalid == 'duplicate': payload['figures'].append(copy.deepcopy(figure))
    if invalid == 'missing_asset': figure['image_asset']['status'] = 'unresolved'
    layout = [{'layout_id': 't', 'type': 'table', 'status': 'EXTRACTED'}]
    result = ledger.reconcile_layout('EXTRACTED', layout, payload)
    assert result['complete'] is (invalid is None)
    if invalid is None:
        assert not result['unmatched_payload_layout_ids']
        assert result['identified'] == 1
