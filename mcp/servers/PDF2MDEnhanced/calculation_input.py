"""Lossless request framing for already-extracted calculation text; no model calls."""
from copy import deepcopy
import re

MATH = re.compile(r'\$\$[\s\S]*?\$\$|(?<![\\$])\$(?:\\.|[^$\\])+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]')


def calculation_source_sections(text):
    """Keep exact offsets; split only outside complete math, never infer item types."""
    spans = list(MATH.finditer(text))
    lines = []
    start = 0
    for match in re.finditer('\n', text):
        if not any(m.start() <= match.start() < m.end() for m in spans):
            lines.append((start, match.start())); start = match.end()
    lines.append((start, len(text)))
    lines = [(a + len(text[a:b]) - len(text[a:b].lstrip()), b - len(text[a:b]) + len(text[a:b].rstrip()))
             for a, b in lines if text[a:b].strip()]
    sections = []
    current = None
    for index, (a, b) in enumerate(lines):
        value = text[a:b]
        # A short standalone label followed by math is a boundary, not a semantic classification.
        next_math = index + 1 < len(lines) and MATH.match(text, lines[index + 1][0]) is not None
        heading = (next_math and len(value) <= 160 and not MATH.search(value)
                   and not re.search(r'[$\\=<>。.!?;；]', value)
                   and (value[:1].isupper() or re.search(r'[\u4e00-\u9fff]', value)))
        if heading:
            current = {'id': f's{len(sections) + 1}', 'title': value, 'source_range': [a, b], 'items': []}
            sections.append(current)
            continue
        if current is None:
            current = {'id': f's{len(sections) + 1}', 'title': '', 'items': []}
            sections.append(current)
        math = [m for m in spans if a <= m.start() and m.end() <= b]
        # Split neighboring complete formulas only when the line begins with a formula.
        separate = (math and math[0].start() == a
                    and all(not text[left.end():right.start()].strip() for left, right in zip(math, math[1:])))
        boundaries = [a] + ([m.start() for m in math[1:]] if separate else []) + [b]
        for left, right in zip(boundaries, boundaries[1:]):
            while right > left and text[right - 1].isspace():
                right -= 1
            if left < right:
                current['items'].append({'id': f"{current['id']}-i{len(current['items']) + 1}",
                                         'text': text[left:right], 'source_range': [left, right]})
    if len(sections) > 100 or sum(len(s['items']) for s in sections) > 500:
        raise ValueError('input_budget_exceeded')
    return sections


def parse_framed_calculation(raw, ctx, item, parse):
    """Reconcile source units through the existing validator; failed analysis stays editable."""
    sections = ctx['source_sections']
    units = {u['id']: u for section in sections for u in section['items']}
    matches = {key: [] for key in units}
    rejected = []
    if isinstance(raw, dict) and isinstance(raw.get('sections'), list):
        for section in raw['sections']:
            if not isinstance(section, dict) or not isinstance(section.get('items'), list):
                continue
            for entry in section['items']:
                if not isinstance(entry, dict):
                    rejected.append({'reason': 'invalid_calculation_item', 'candidate': deepcopy(entry)})
                    continue
                key = entry.get('source_item_id')
                if key is None:
                    # Existing exact citations can still identify a unique unit; never guess duplicates.
                    quotes = entry.get('sources')
                    candidates = [u['id'] for u in units.values() if isinstance(quotes, list) and quotes
                                  and all(isinstance(q, str) and q.strip() and q in u['text'] for q in quotes)]
                    if len(candidates) == 1:
                        key = candidates[0]
                if isinstance(key, str) and key in units:
                    matches[key].append(entry)
                else:
                    rejected.append({'reason': 'invalid_source_item_id', 'candidate': deepcopy(entry)})
    proposal = deepcopy(raw) if isinstance(raw, dict) else {}
    proposal['sections'] = []
    for section in sections:
        entries = []
        for unit in section['items']:
            candidates = matches[unit['id']]
            if len(candidates) == 1:
                entry = deepcopy(candidates[0])
                # ID refers to trusted input evidence; do not let generated quotes change it.
                entry['sources'] = [unit['text']]
                entry['source_ranges'] = [unit['source_range']]
            else:
                entry = {'kind': 'unresolved'}  # The validator records this, then we restore the raw unit.
                if len(candidates) > 1:
                    rejected.extend({'reason': 'duplicate_source_item_id', 'candidate': deepcopy(c)} for c in candidates)
            entries.append(entry)
        proposal['sections'].append({'title': section['title'], 'items': entries})
    sheet = parse(proposal, ctx, item)
    accepted = {entry['id']: entry for section in sheet['sections'] for entry in section['items']}
    rebuilt = []
    index = 0
    pending = False
    for section in sections:
        output = {'title': section['title'], 'items': []}
        for unit in section['items']:
            index += 1
            identifier = f'item-{index}'
            entry = accepted.get(identifier)
            if entry is None:
                pending = True
                entry = {'id': identifier, 'kind': 'note', 'name': unit['id'], 'content': unit['text'],
                         'semantic_desc': '', 'semantic_status': 'missing', 'review_status': 'needs_completion',
                         'rejected_fields': [{'field': 'analysis', 'reason': 'source_item_needs_completion'}],
                         'source': {'sha256': ctx.get('sha256'), 'text_ranges': [unit['source_range']],
                                    **{k: deepcopy(item[k]) for k in ('layout_id', 'bbox', 'bbox_space') if k in item},
                                    'location_scope': 'source_text'}}
            if not entry.get('semantic_desc'):
                entry['review_status'] = 'needs_completion'
            entry['source_item_id'] = unit['id']
            output['items'].append(entry)
        rebuilt.append(output)
    sheet['sections'] = rebuilt
    if rejected:
        sheet.setdefault('rejected_items', []).extend(rejected)
    if pending or rejected:
        sheet['validation_status'] = 'unresolved'
        sheet['unresolved'].append({'reason': 'source_item_needs_completion'})
    if pending:
        sheet['semantic_status'] = 'missing'
        if 'calculation_semantics_missing' not in sheet['diagnostics']:
            sheet['diagnostics'].append('calculation_semantics_missing')
    return sheet
