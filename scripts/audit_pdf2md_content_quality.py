"""Offline snapshot audit. No storage, network, providers, or source text in output.

.venv/bin/python scripts/audit_pdf2md_content_quality.py --input snapshot.json \
    --output /tmp/quality.json [--pandas-reference /tmp/pandas-result.json]
The optional reference must come from a fresh independent pandas probe. Equality
is a grid comparison, never proof of source image accuracy or header semantics.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp' / 'servers'))
from PDF2MDEnhanced.single_page_tools import _html_table_to_grid
from PDF2MDEnhanced.table_query import IDENTITY, _sources, enhance_table


def audit(bundles, reference=(), query_specs=()):
    rows = []
    queries = []
    def forbidden(_):
        raise AssertionError('Offline audit must never create a provider')
    for sample, bundle in enumerate(bundles, 1):
        for index, table in enumerate(bundle['tables'], 1):
            markup = table.get('render_html')
            if not markup:
                continue
            try:
                grid, meta = _html_table_to_grid(markup)
            except ValueError:
                grid, meta = [], {}
            identity = {key: table.get(key, str(table.get('_id', ''))) for key in IDENTITY}
            target = {**identity, **{k: table[k] for k in ('page_no', 'override_revision') if k in table}}
            request = {'target': target, 'table': {**table, **identity}, 'request_id': 'offline-audit',
                       'source_html_sha256': hashlib.sha256(markup.encode()).hexdigest()}
            out = enhance_table(request, _html_table_to_grid, forbidden)['query_enhancement']
            try:
                sources, positions, _ = _sources(markup, _html_table_to_grid)
                consistent = all(grid[cell['row']][cell['col']] == cell['text'] for cell in sources.values() if 'row' in cell)
                for position, origin in positions.items():
                    if not position.startswith('r'):
                        continue
                    r, c = map(int, position[1:].split('c'))
                    consistent = consistent and grid[r][c] == sources[origin]['text']
            except (ValueError, IndexError):
                consistent = False
            matches = [t for t in reference if all(t.get(k) == table.get(k) for k in ('doc_id', 'version', 'table_id'))]
            for spec in query_specs:
                if all(spec.get(k) == table.get(k) for k in ('doc_id', 'version', 'table_id')):
                    queries.extend(verify_queries(grid, out, spec))
            rows.append({'sample': sample, 'table': index, 'page': table.get('page_no'),
                         'parsed': bool(grid), 'coordinate_consistent': consistent,
                         'pandas_grid_equal': grid == matches[0].get('grid') if len(matches) == 1 else None,
                         'grid_warnings': meta.get('warnings', []), 'lookup_status': out['lookup_status'],
                         'reasons': sorted({i['reason'] for i in out['unresolved']}), 'model_calls': out['model_calls']})
    return {'html_tables': len(rows), 'parsed': sum(r['parsed'] for r in rows),
            'coordinate_consistent': sum(r['coordinate_consistent'] for r in rows),
            'pandas_equal': sum(r['pandas_grid_equal'] is True for r in rows),
            'automatic_complete': sum(r['lookup_status'] == 'complete' for r in rows),
            'blockers': dict(Counter(reason for r in rows for reason in r['reasons'])), 'tables': rows,
            'query_cases': queries, 'manual_passed': sum(q['manual_passed'] for q in queries),
            'automatic_query_passed': sum(q['automatic_status'] == 'passed' for q in queries)}



def verify_queries(grid, projection, spec):
    """Manual indices are used only by the manual comparator, never by enhancement."""
    results = []
    for ordinal, case in enumerate(spec['cases'], 1):
        manual = []
        for r in range(spec['data_start'], spec['data_stop']):
            for c in range(len(grid[r])):
                if c == spec['row_key_col']:
                    continue
                values = {'row_label': grid[r][spec['row_key_col']]}
                values.update({f'header_{i+1}': grid[h][c] for i, h in enumerate(spec['header_rows'])})
                if all(values.get(k) == v for k, v in case['where'].items()):
                    manual.append(grid[r][c])
        automatic = []
        available = projection['lookup_status'] == 'complete'
        if available:
            for section in projection['lookup_sections']:
                for record in section['records']:
                    if record['conditions']:
                        available = False
                        continue
                    keys = [v['raw_text'] for v in record['values'].values()
                            if v['position'].endswith(f"c{spec['row_key_col']}")]
                    for field in section['fields']:
                        value = record['values'][field['key']]
                        if value['position'].endswith(f"c{spec['row_key_col']}"):
                            continue
                        values = {'row_label': keys[0] if len(keys) == 1 else None}
                        values.update({f'header_{i+1}': h['raw_text'] for i,h in enumerate(field['header_path'])})
                        if all(values.get(k) == v for k,v in case['where'].items()):
                            automatic.append(value['raw_text'])
        results.append({'case': ordinal, 'manual_passed': manual == case['expected_values'],
                        'automatic_status': 'unavailable' if not available else
                                            'passed' if automatic == case['expected_values'] else 'failed'})
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pandas-reference', type=Path)
    parser.add_argument('--query-spec', type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    reference = json.loads(args.pandas_reference.read_text())['tables'] if args.pandas_reference else []
    specs = json.loads(args.query_spec.read_text()) if args.query_spec else []
    result = audit(json.loads(raw), reference, specs)
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'tables'}))
