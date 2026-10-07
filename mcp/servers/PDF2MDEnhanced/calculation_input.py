"""Lossless request framing for already-extracted calculation text; no model calls."""
from copy import deepcopy
import re

MATH = re.compile(r'\$\$[\s\S]*?\$\$|(?<![\\$])\$(?:\\.|[^$\\])+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]')


MATH_TOKEN = re.compile(r'(?<!\\)(?:\$\$|\$|\\[\[\]()]|\\(?:begin|end)\{[^{}]+\})')


def math_spans(text):
    """Protect nested environments and preserve an unclosed tail without guessing."""
    stack = []
    start = None
    spans = []
    for token in MATH_TOKEN.finditer(text):
        value = token.group()
        if stack and value == stack[-1]:
            stack.pop()
            if not stack:
                spans.append((start, token.end(), True))
        elif value.startswith(r'\begin{'):
            if not stack:
                start = token.start()
            stack.append(value.replace(r'\begin', r'\end', 1))
        elif not stack and value in ('$', '$$', r'\[', r'\('):
            start = token.start()
            stack.append({r'\[': r'\]', r'\(': r'\)'}.get(value, value))
    if stack:
        spans.append((start, len(text), False))
    return spans


def math_content(text):
    values = []
    for start, end, complete in math_spans(text):
        if complete:
            formula = text[start:end]
            delimiter = 2 if formula.startswith(('$$', r'\[', r'\(')) else 1 if formula.startswith('$') else 0
            values.append(formula[delimiter:-delimiter].strip() if delimiter else formula.strip())
    return values


def markdown_table_html(text):
    """Recognize explicit Markdown tables without splitting mathematical pipes/newlines."""
    spans = math_spans(text)
    boundaries = [0] + [m.end() for m in re.finditer('\n', text)
                        if not any(a <= m.start() < b for a, b, _ in spans)] + [len(text)]
    lines = [text[a:b] for a, b in zip(boundaries, boundaries[1:])]

    def cells(line):
        protected = math_spans(line)
        cuts = [m.start() for m in re.finditer(r'(?<!\\)\|', line)
                if not any(a <= m.start() < b for a, b, _ in protected)]
        if not cuts:
            return None
        edges = [-1, *cuts, len(line)]
        values = [line[a + 1:b].strip() for a, b in zip(edges, edges[1:])]
        if not values[0]:
            values.pop(0)
        if values and not values[-1]:
            values.pop()
        return values if len(values) > 1 else None

    output = []
    index = 0
    while index < len(lines):
        header = cells(lines[index])
        separator = cells(lines[index + 1]) if index + 1 < len(lines) else None
        if (header and separator and len(header) == len(separator)
                and all(re.fullmatch(r':?-{3,}:?', c) for c in separator)):
            output.append('<table><tr>' + ''.join('<th>' + c + '</th>' for c in header) + '</tr>')
            index += 2
            while index < len(lines):
                row = cells(lines[index])
                if not row or len(row) != len(header):
                    break
                output.append('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>')
                index += 1
            output.append('</table>\n')
        else:
            output.append(lines[index])
            index += 1
    return ''.join(output)


def calculation_source_sections(text, table_rows=None):
    if table_rows:
        sections = []
        cursor = 0

        def append_part(start, end, context=()):
            for section in calculation_source_sections(text[start:end]):
                section['id'] = f's{len(sections) + 1}'
                if 'source_range' in section:
                    section['source_range'] = [n + start for n in section['source_range']]
                for index, unit in enumerate(section['items'], 1):
                    unit['id'] = f"{section['id']}-i{index}"
                    unit['source_range'] = [n + start for n in unit['source_range']]
                    if context:
                        unit['row_context'] = deepcopy(context)
                sections.append(section)

        for row in table_rows:
            cells = row['cells']
            start, end = row['source_range']
            append_part(cursor, start)
            for index, cell in enumerate(cells):
                append_part(*cell['source_range'], [c for j, c in enumerate(cells) if j != index])
            cursor = end
        append_part(cursor, len(text))
        if len(sections) > 100 or sum(len(s['items']) for s in sections) > 500:
            raise ValueError('input_budget_exceeded')
        return sections

    """Keep exact offsets; split only outside complete math, never infer item types."""
    spans = math_spans(text)
    lines = []
    start = 0
    for match in re.finditer('\n', text):
        if not any(a <= match.start() < b for a, b, _ in spans):
            lines.append((start, match.start())); start = match.end()
    lines.append((start, len(text)))
    lines = [(a + len(text[a:b]) - len(text[a:b].lstrip()), b - len(text[a:b]) + len(text[a:b].rstrip()))
             for a, b in lines if text[a:b].strip()]
    sections = []
    current = None
    explicit_headings = any(re.match(r'^#{1,6}\s+\S', text[a:b]) for a, b in lines)
    for index, (a, b) in enumerate(lines):
        value = text[a:b]
        if (current and current['items'] and math_spans(current['items'][-1]['text'])
                and re.match(r'^(?:(?:Exception|Note)\s*:|Except\b|Unless\b|注[:：]|例外[:：])', value, re.I)):
            previous = current['items'][-1]
            previous['source_range'][1] = b
            previous['text'] = text[previous['source_range'][0]:b]
            continue
        # A standalone label before an expression/definition marks a boundary, not an item type.
        following = text[slice(*lines[index + 1])] if index + 1 < len(lines) else ''
        next_math = index + 1 < len(lines) and any(a == lines[index + 1][0] for a, _, _ in spans)
        next_definition = bool(re.match(r'^[^\s=—–:]{1,80}\s*[—–:]\s+\S', following))
        heading = bool(re.match(r'^#{1,6}\s+\S', value)) or (not explicit_headings and (next_math or next_definition) and len(value) <= 160 and not MATH.search(value)
                   and not re.search(r'[$\\=<>。.!?;；]', value)
                   and (value[:1].isupper() or re.search(r'[\u4e00-\u9fff]', value)))
        if heading:
            current = {'id': f's{len(sections) + 1}', 'title': re.sub(r'^#{1,6}\s+', '', value),
                       'source_range': [a, b], 'items': []}
            sections.append(current)
            continue
        if current is None:
            current = {'id': f's{len(sections) + 1}', 'title': '', 'items': []}
            sections.append(current)
        math = [(left, right) for left, right, complete in spans if complete and a <= left and right <= b]
        # Split neighboring complete formulas only when the line begins with a formula.
        separate = (math and math[0][0] == a
                    and all(not text[left[1]:right[0]].strip() for left, right in zip(math, math[1:])))
        boundaries = [a] + ([left for left, _ in math[1:]] if separate else []) + [b]
        for left, right in zip(boundaries, boundaries[1:]):
            while right > left and text[right - 1].isspace():
                right -= 1
            if left < right:
                current['items'].append({'id': f"{current['id']}-i{len(current['items']) + 1}",
                                         'text': text[left:right], 'source_range': [left, right],
                                         'math': math_content(text[left:right])})
    if len(sections) > 100 or sum(len(s['items']) for s in sections) > 500:
        raise ValueError('input_budget_exceeded')
    return sections


def parse_framed_calculation(raw, ctx, item, parse):
    """Bind generated fields to deterministic units; retain every rejected source."""
    sections = ctx['source_sections']
    units = {u['id']: u for section in sections for u in section['items']}
    headings = {u['id']: {'text': ctx['text'][slice(*section['source_range'])],
                          'source_range': section['source_range']}
                for section in sections if section.get('source_range')
                for u in section['items']}
    document_headings = []
    for section in sections:
        if section['items']:
            break
        if section.get('source_range'):
            document_headings.append({'text': ctx['text'][slice(*section['source_range'])],
                                      'source_range': section['source_range']})
    matches = {key: [] for key in units}
    rejected = []
    revision_ok = not isinstance(raw, dict) or raw.get('source_revision', ctx.get('source_revision')) == ctx.get('source_revision')
    if not revision_ok:
        rejected.append({'reason': 'calculation_source_revision_mismatch'})
    if revision_ok and isinstance(raw, dict) and isinstance(raw.get('sections'), list):
        for section in raw['sections']:
            for entry in section.get('items', []) if isinstance(section, dict) and isinstance(section.get('items'), list) else []:
                if not isinstance(entry, dict):
                    rejected.append({'reason': 'invalid_calculation_item', 'candidate': deepcopy(entry)})
                    continue
                key = entry.get('source_item_id')
                if key is None and 'source_item_ids' not in entry:
                    quotes = entry.get('sources')
                    possible = [u['id'] for u in units.values() if isinstance(quotes, list) and quotes
                                and all(isinstance(q, str) and q.strip() and q in u['text'] for q in quotes)]
                    if len(possible) == 1:
                        key = possible[0]
                keys = entry.get('source_item_ids', [key])
                if (not isinstance(keys, list) or not keys or len(keys) > 50
                        or not all(isinstance(k, str) and k in units for k in keys)
                        or len(set(keys)) != len(keys) or key != keys[0]):
                    rejected.append({'reason': 'invalid_source_item_id', 'candidate': deepcopy(entry)})
                    continue
                candidate = {'entry': deepcopy(entry), 'keys': keys}
                for key in keys:
                    matches[key].append(candidate)
    invalid = set()
    for values in matches.values():
        if len(values) > 1:
            parts = [c['entry'].get('source_part_id') for c in values]
            if not all(isinstance(p, str) and 0 < len(p) <= 128 for p in parts) or len(set(parts)) != len(parts):
                for candidate in values:
                    invalid.add(id(candidate))
                    rejected.append({'reason': 'duplicate_source_item_id', 'candidate': candidate['entry']})
    proposal = deepcopy(raw) if isinstance(raw, dict) else {}
    proposal['sections'] = []
    bindings = {}
    index = 0
    for section in sections:
        entries = []
        for unit in section['items']:
            for candidate in matches[unit['id']]:
                if id(candidate) in invalid or candidate['keys'][0] != unit['id']:
                    continue
                entry = deepcopy(candidate['entry'])
                formulas = math_content(unit['text'])
                if not formulas and entry.get('latex_source_index') is None:
                    entry.pop('latex_source_index', None)
                if ('latex_source_index' in entry or
                        (len(formulas) == 1 and len(candidate['keys']) == 1 and not entry.get('latex'))):
                    selection = entry.pop('latex_source_index', 0)
                    if (type(selection) is not int or len(candidate['keys']) != 1
                            or not 0 <= selection < len(formulas)
                            or entry.get('latex') not in (None, '', formulas[selection])):
                        rejected.append({'reason': 'invalid_math_source_index', 'candidate': candidate['entry']})
                        continue
                    entry['latex'] = formulas[selection]
                    if entry.get('kind') == 'check' and not entry.get('checks'):
                        entry['checks'] = [formulas[selection]]
                latex = entry.get('latex')
                if isinstance(latex, str) and latex and not any(
                        latex in units[key]['text'] or any(value in units[key]['math'] for value in math_content(latex))
                        for key in candidate['keys']):
                    rejected.append({'reason': 'formula_source_mismatch', 'candidate': candidate['entry']})
                    continue
                citations = []
                for key in candidate['keys']:
                    for source in [units[key], *units[key].get('row_context', []), *ctx.get('document_preamble', []), *document_headings, *([headings[key]] if key in headings else [])]:
                        if source['source_range'] not in [c['source_range'] for c in citations]:
                            citations.append(source)
                # Restore presentation-only whitespace in generated references to the
                # exact cited source. Formulas, checks and conditions remain literal.
                if isinstance(entry.get('references'), list):
                    for position, value in enumerate(entry['references']):
                        if not isinstance(value, str) or not value.strip():
                            continue
                        pattern = r'\s+'.join(re.escape(word) for word in value.split())
                        for source in citations:
                            match = re.search(pattern, source['text'])
                            if match:
                                entry['references'][position] = match.group(0)
                                break
                entry['sources'] = [source['text'] for source in citations]
                entry['source_ranges'] = [source['source_range'] for source in citations]
                index += 1
                bindings[f'item-{index}'] = candidate
                entries.append(entry)
        # The base validator requires nonempty sections. Empty headings are restored below.
        if entries:
            proposal['sections'].append({'title': section['title'], 'items': entries})
    sheet = parse(proposal, ctx, item)
    sheet.setdefault('semantic_status', 'missing')
    sheet.setdefault('semantic_desc', '')
    accepted = {entry['id']: entry for section in sheet['sections'] for entry in section['items']}
    outputs = {key: [] for key in units}
    represented = set()
    structured = set()
    review = {key for identifier, candidate in bindings.items() if identifier not in accepted for key in candidate['keys']}
    for identifier, entry in accepted.items():
        candidate = bindings[identifier]
        keys = candidate['keys']
        entry['content'] = '\n'.join(units[key]['text'] for key in keys)
        entry['source_item_id'] = keys[0]
        contexts = [c for key in keys for c in units[key].get('row_context', [])]
        if contexts:
            entry['source']['row_context'] = deepcopy(contexts)
        if len(keys) > 1:
            entry['source_item_ids'] = keys
        if candidate['entry'].get('source_part_id'):
            entry['source_part_id'] = candidate['entry']['source_part_id']
        entry['source'].update(source_revision=ctx.get('source_revision'), range_unit='unicode_codepoint', location_scope='source_text')
        if entry.get('rejected_fields') or any(key in review for key in keys):
            entry['review_status'] = 'needs_completion'
            review.update(keys)
        represented.update(keys)
        structured.update(keys)
        outputs[keys[0]].append(entry)
    for key, unit in units.items():
        equations = [value for value in math_content(unit['text']) if re.search(r'[=<>]|\\(?:le|ge|lt|gt|neq)\b', value)]
        results = [entry for entries in outputs.values() for entry in entries
                   if key in entry.get('source_item_ids', [entry['source_item_id']])]
        if any(not any(value == entry.get('latex') or value in entry.get('checks', [])
                          or any(value in condition for condition in entry.get('conditions', [])) for entry in results)
               for value in equations):
            review.add(key)
            for entry in results:
                entry['review_status'] = 'needs_completion'
            sheet['unresolved'].append({'reason': 'formula_needs_completion', 'source_item_id': key})
            sheet['validation_status'] = 'unresolved'
    rebuilt = []
    for section in sections:
        output = {'title': section['title'], 'items': [], 'source_section_id': section['id']}
        if 'source_range' in section:
            output['source_range'] = section['source_range']
        for unit in section['items']:
            output['items'].extend(outputs[unit['id']])
            if unit['id'] in represented:
                continue
            index += 1
            output['items'].append({'id': f'item-{index}', 'kind': 'note', 'name': unit['id'], 'content': unit['text'],
                'semantic_desc': '', 'semantic_status': 'missing', 'review_status': 'needs_completion',
                'source_item_id': unit['id'],
                'rejected_fields': [{'field': 'analysis', 'reason': 'source_item_needs_completion'}],
                'source': {'sha256': ctx.get('sha256'), 'text_ranges': [unit['source_range']],
                           **({'row_context': deepcopy(unit['row_context'])} if unit.get('row_context') else {}),
                           'source_revision': ctx.get('source_revision'), 'range_unit': 'unicode_codepoint',
                           **{k: deepcopy(item[k]) for k in ('layout_id', 'bbox', 'bbox_space') if k in item},
                           'location_scope': 'source_text'}})
            review.add(unit['id'])
        rebuilt.append(output)
    sheet['sections'] = rebuilt
    sheet['source_revision'] = ctx.get('source_revision')
    sheet['coverage'] = {'input_units': len(units), 'represented': len(units),
                         'structured': len(structured), 'needs_review': len(review)}
    if rejected:
        sheet.setdefault('rejected_items', []).extend(rejected)
    if len(structured) < len(units) or rejected:
        sheet['validation_status'] = 'unresolved'
        sheet['unresolved'].append({'reason': 'source_item_needs_completion'})
    if sheet.get('semantic_status') == 'missing':
        sheet['semantic_status'] = 'missing'
        if 'calculation_semantics_missing' not in sheet['diagnostics']:
            sheet['diagnostics'].append('calculation_semantics_missing')
    if any(not complete for _, _, complete in math_spans(ctx['text'])):
        sheet['validation_status'] = 'unresolved'
        sheet['unresolved'].append({'reason': 'calculation_math_unclosed'})
    return sheet
