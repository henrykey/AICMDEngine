"""Calculation items are source-bound sequences, never rectangular lookup data."""
from copy import deepcopy
import hashlib
import html
from html.parser import HTMLParser
import json
import math
import re

from .layout_ledger import validate_recovered_object
from .semantic_language import detect_description_language, description_mismatch, valid_description

KINDS = {'data_table', 'calculation_sheet', 'mixed', 'uncertain'}
ITEM_KINDS = {'input', 'formula', 'branch', 'check', 'reference', 'note'}
METADATA_KEYS = ('table_kind', 'table_classification', 'calculation_sheet', 'lookup_status',
                 'lookup_sections', 'manualReviewRequired', 'degraded', 'content_format',
                 'table_kind_source', 'continuation')


class PhysicalRequestBudgetExceeded(RuntimeError):
    def __init__(self):
        super().__init__('table_analysis_physical_budget_exhausted')


class _SourceText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {'br', 'p', 'td', 'th', 'tr', 'table', 'caption', 'div'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'p', 'td', 'th', 'tr', 'table', 'caption', 'div'}:
            self.parts.append('\n')


def source_context(content):
    """No grid inference: preserve text, math and sequence even for broken spans."""
    if not isinstance(content, str) or len(content) > 100000:
        return {'status': 'input_budget_exceeded', 'text': ''}
    if re.search(r'<(?:table|td|th)\b', content, re.I):
        # Mathematical comparisons are text, not HTML tags (for example $S<S_a$).
        math_pattern = r'\$\$[\s\S]*?\$\$|(?<!\\)\$(?:\\.|[^$\\])+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]'
        protected = re.sub(math_pattern, lambda match: match.group().replace('<', '&lt;').replace('>', '&gt;'), content)
        parser = _SourceText(); parser.feed(protected)
        text = ''.join(parser.parts)
    else:
        text = content
    return {'status': 'available', 'sha256': hashlib.sha256(content.encode()).hexdigest(),
            'text': '\n'.join(line.strip() for line in text.splitlines() if line.strip())}


def classification_prompt(include_items=True):
    guidance = (
        ' Blank input/result slots are intentional in calculation templates; do not fill them or mark them omitted. '
        'A continuation containing only symbols or acceptance criteria can belong to a calculation sheet. '
        'Return continuation_required=true when the image has a continuation marker or type needs adjacent context. '
        'Fixed-axis formula lookup tables remain data_table even if the title says calculation. '
    )
    classification = (
        " Classify each table from the IMAGE as table_kind=data_table|calculation_sheet|mixed|uncertain. "
        "Return classification_evidence as exact unique quotes from calculation_source.text only. "
        "Calculation sheets organize parameters, formulas, branches and checks; panels are not cross-indexed "
        "data records. A title or isolated formula is insufficient. Never quote prior generated descriptions. "
        "In this classification call do not extract calculation items; a dedicated call handles them. "
    )
    if not include_items:
        return classification + guidance
    return guidance + (
        ' For each table also return table_kind=data_table|calculation_sheet|mixed|uncertain, '
        'classification_evidence=[exact quotes from calculation_source.text]. Classify using the IMAGE: '
        'a calculation_sheet organizes inputs, formulas, branches, checks and references; rules and '
        'side-by-side panels are layout, NOT cross-indexed records. A formula in a data cell or a title '
        'alone is not sufficient evidence. For mixed/uncertain preserve the source and request review. '
        'Never quote a prior description, title or context unless it occurs literally in calculation_source.text. '
        'A calculation_sheet response without sections/items is incomplete: do not return only descriptions. '
        'For calculation_sheet ONLY, return calculation_sheet={sections:[{title:"",items:[{'
        'kind:"input|formula|branch|check|reference|note",name:"",sources:["exact unique source quote"],'
        'symbol:"",latex:"",unit:"",conditions:[],checks:[],references:[],bbox:[]}]}],unresolved:[],'
        'image_discrepancies:[]}. Read groups in their semantic order; never pair left and right panels '
        'by height. Each item must cite exact unique quotes from calculation_source.text, including '
        'its complete formula, unit, conditions and attached notes. All extracted name/symbol/latex/unit '
        'and list entries must be literal substrings of the cited quotes. Section titles may be generated '
        'in the requested description language. Cover every source character with an item or explicitly '
        'list the unreadable/omitted parts in unresolved. Preserve whole piecewise expressions with '
        'their conditions. Never calculate, invent values or resolve external figures. Express only source-supported input/output relationships. '
        'If the IMAGE disagrees with OCR, record image_discrepancies; do not silently replace OCR. '
        'No grid/normalized_rows/lookup_sections are required for calculation sheets. '
        'These are derived items alongside the original OCR, never replacement table content. '
        'If calculation_source is not supplied, retain the full transcription in markdown and quote its '
        'decoded visible text (HTML cell boundaries become newlines). For calculation sheets this overrides '
        'grid-only instructions; retain every footnote and do not flatten panels into data rows. '
        'For each item return bbox=[x0,y0,x1,y1] normalized to the supplied page image, only when its '
        'region is clear and inside the source table bbox. Otherwise return [] and request location review. '
    )


def _quote_range(text, quote):
    if not isinstance(quote, str) or not quote.strip() or text.count(quote) != 1:
        raise ValueError('invalid_source_reference')
    start = text.index(quote)
    return start, start + len(quote)



def _source_ranges(text, quotes, supplied=None):
    if supplied is None:
        return [_quote_range(text, quote) for quote in quotes]
    if not isinstance(supplied, list) or len(supplied) != len(quotes):
        raise ValueError('invalid_source_reference')
    for quote, span in zip(quotes, supplied):
        if (not isinstance(quote, str) or not quote.strip() or not isinstance(span, list) or len(span) != 2
                or not all(type(n) is int for n in span) or not 0 <= span[0] < span[1] <= len(text)
                or text[span[0]:span[1]] != quote):
            raise ValueError('invalid_source_reference')
    return supplied

def _render(sections, language="en"):
    def escape(value):
        return html.escape(value, quote=False).replace('|', '&#124;').replace('\n', '<br>')
    rows = ['| 项目／步骤 | 内容 |' if language == 'zh' else '| Item / step | Content |', '| --- | --- |']
    for section in sections:
        rows.append('| **' + escape(section['title']) + '** | |')
        for item in section['items']:
            rows.append('| ' + escape(item['name']) + ' | ' + escape(item['content']) + ' |')
    return '\n'.join(rows)


def apply_calculation_sheet(item, candidate, content, description_language="unknown"):
    """Validate a single identity-matched VLM proposal; no model calls or source writes."""
    if 'table_kind' not in candidate:
        item.setdefault('table_classification', {'status': 'not_run', 'reason': 'classification_not_run'})
        return
    ctx = source_context(content)
    ctx['description_language'] = description_language
    text = ctx['text']
    kind = candidate.get('table_kind')
    evidence = candidate.get('classification_evidence')
    reason = None
    try:
        if ctx['status'] != 'available':
            raise ValueError(ctx['status'])
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError('classification_kind_invalid')
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
            raise ValueError('classification_evidence_missing')
        for quote in evidence:
            if not isinstance(quote, str) or not quote.strip() or quote not in text:
                raise ValueError('classification_evidence_mismatch')
            if text.count(quote) != 1:
                raise ValueError('classification_evidence_ambiguous')
    except ValueError as exc:
        reason = str(exc)
        kind = 'uncertain'
    item['table_kind'] = kind
    item['table_kind_source'] = 'automatic'
    item['table_classification'] = {'kind': kind, 'status': 'unresolved' if kind == 'uncertain' else 'model_proposed',
                                    'evidence': deepcopy(evidence) if kind != 'uncertain' else [],
                                    'proposed_kind': candidate.get('table_kind') if isinstance(candidate.get('table_kind'), str) and len(candidate['table_kind']) <= 32 else None,
                                    'source_sha256': ctx.get('sha256')}
    if reason or kind == 'uncertain':
        item['table_classification']['reason'] = reason or 'classification_model_uncertain'
    if candidate.get('continuation_required') is True or kind == 'uncertain':
        item['continuation'] = {'status': 'pending', 'reason': 'adjacent_context_required'}
    if kind == 'data_table':
        return
    item.update(lookup_status='unavailable', lookup_sections=[], manualReviewRequired=True, degraded=True)
    for key in ('contained_formulas', 'contained_formula_sources', 'contained_formula_quality'):
        item.pop(key, None)
    for key in ('columns', 'normalized_rows', 'source_cells', 'cell_status'):
        if key in item:
            item[key] = []
    if 'tableRowsContent' in item:
        item['tableRowsContent'] = ''
    if kind != 'calculation_sheet':
        if kind == 'mixed':
            item['table_classification']['reason'] = 'mixed_requires_partition'
        return

    item['content_format'] = 'calculation_sheet_json'
    item['calculation_sheet'] = parse_calculation_sheet(candidate.get('calculation_sheet'), ctx, item)
    if item['calculation_sheet'].get('semantic_desc'):
        item['semantic_desc'] = item['calculation_sheet']['semantic_desc']
        item['description'] = item['semantic_desc']


def parse_calculation_sheet(raw, ctx, item):
    """Validate and render calculation steps without interpreting table geometry."""
    text = ctx['text']
    language = ctx.get('description_language')
    if language in (None, '', 'unknown'):
        language = detect_description_language(text)
    sheet = {'contract_version': '1', 'source_sha256': ctx.get('sha256'),
             'source_text': text, 'sections': [], 'unresolved': [],
             'validation_status': 'unresolved', 'quality_status': 'needs_review',
             'image_verified': False, 'diagnostics': ['source_bound_not_image_verified']}
    covered = bytearray(len(text))
    def issue(reason):
        if {'reason': reason} not in sheet['unresolved']:
            sheet['unresolved'].append({'reason': reason})
    if not isinstance(raw, dict) or len(json.dumps(raw, ensure_ascii=False)) > 200000:
        issue('invalid_calculation_sheet'); return sheet
    sections = raw.get('sections')
    if not isinstance(sections, list) or not 1 <= len(sections) <= 100:
        issue('invalid_calculation_sheet'); return sheet
    item_count = 0
    for section_index, section in enumerate(sections):
        if (not isinstance(section, dict) or not isinstance(section.get('title'), str)
                or not isinstance(section.get('items'), list) or not section['items']):
            issue('invalid_calculation_section'); continue
        if section['title'] not in text and description_mismatch(section['title'], language):
            issue('section_title_language_mismatch')
            continue
        output = {'title': section['title'], 'items': []}
        sheet['sections'].append(output)
        for item_index, entry in enumerate(section['items']):
            item_count += 1
            if item_count > 500:
                issue('input_budget_exceeded'); break
            field = 'kind'
            try:
                if not isinstance(entry, dict) or entry.get('kind') not in ITEM_KINDS:
                    raise ValueError('invalid_calculation_item')
                field = 'sources'
                quotes = entry.get('sources')
                if not isinstance(quotes, list) or not 1 <= len(quotes) <= 50:
                    raise ValueError('invalid_source_reference')
                ranges = _source_ranges(text, quotes, entry.get('source_ranges'))
                body = '\n'.join(quotes)
                result = {'id': f'item-{item_count}', 'kind': entry['kind'], 'content': body}
                for key in ('name', 'symbol', 'latex', 'unit') + (('value',) if 'value' in entry else ()):
                    field = key
                    value = entry.get(key, '')
                    if not isinstance(value, str) or (value and not any(value in q for q in quotes)):
                        if key == 'latex':
                            raise ValueError('formula_source_mismatch')
                        issue('field_source_mismatch')
                        result.setdefault('rejected_fields', []).append({'field': key, 'candidate': deepcopy(value),
                                                                       'reason': 'field_source_mismatch'})
                        value = ''
                    result[key] = value
                field = 'name'
                if not result['name'].strip():
                    # A missing label must not erase a correctly transcribed equation.
                    result['name'] = result['symbol'] or result['latex'] or quotes[0]
                field = 'latex'
                if result['latex']:
                    reason, _ = validate_recovered_object({'type': 'formula', 'layout_id': 'item'},
                        {'type': 'formula', 'layout_id': 'item', 'status': 'EXTRACTED',
                         'complete': True, 'latex': result['latex']})
                    if reason:
                        raise ValueError(reason)
                for key in ('conditions', 'checks', 'references'):
                    field = key
                    values = entry.get(key, [])
                    if not isinstance(values, list) or not all(isinstance(v, str) and v and any(v in q for q in quotes) for v in values):
                        raise ValueError('field_source_mismatch')
                    result[key] = deepcopy(values)
                field = 'latex'
                if entry['kind'] in {'formula', 'branch'} and not result['latex']:
                    raise ValueError('formula_missing')
                field = 'conditions'
                if entry['kind'] == 'branch' and not result['conditions']:
                    raise ValueError('conditions_missing')
                field = 'checks'
                if entry['kind'] == 'check' and not result['checks']:
                    raise ValueError('checks_missing')
                result['source'] = {'sha256': ctx['sha256'], 'text_ranges': [list(r) for r in ranges],
                                    **{k: deepcopy(item[k]) for k in ('layout_id', 'bbox', 'bbox_space') if k in item},
                                    'location_scope': 'table'}
                field = 'bbox'
                bbox = entry.get('bbox')
                if bbox:
                    parent = item.get('bbox', [0, 0, 1, 1])
                    if (not isinstance(bbox, list) or len(bbox) != 4
                            or not all(type(v) in (float, int) and math.isfinite(v) for v in bbox)
                            or not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1)
                            or not isinstance(parent, list) or len(parent) != 4
                            or not all(type(v) in (float, int) and math.isfinite(v) for v in parent)
                            or not (parent[0] <= bbox[0] and parent[1] <= bbox[1]
                                    and bbox[2] <= parent[2] and bbox[3] <= parent[3])):
                        raise ValueError('item_bbox_invalid')
                    result['source'].update(bbox=list(bbox), bbox_space='normalized_page', location_scope='item')
                elif 'item_location_unresolved' not in sheet['diagnostics']:
                    sheet['diagnostics'].append('item_location_unresolved')
                for start, end in ranges:
                    covered[start:end] = b'\1' * (end - start)
                _knowledge_fields(entry, result, quotes, language, issue)
                output['items'].append(result)
            except (ValueError, TypeError) as exc:
                reason = str(exc) if isinstance(exc, ValueError) else 'invalid_calculation_item'
                issue(reason)
                sheet.setdefault('rejected_items', []).append({
                    'section_index': section_index, 'section_title': section['title'],
                    'item_index': item_index, 'field': field,
                    'reason': reason, 'candidate': deepcopy(entry),
                })
    missing = [i for i, char in enumerate(text) if not covered[i] and not char.isspace()]
    sheet['unmapped_character_count'] = len(missing)
    if missing:
        issue('unmapped_source_text')
        ranges = []
        start = None
        for index in range(len(text) + 1):
            if index < len(text) and not covered[index]:
                if start is None:
                    start = index
            elif start is not None:
                if text[start:index].strip():
                    ranges.append([start, index])
                start = None
        sheet['unmapped_ranges'] = ranges
    if raw.get('unresolved') != []:
        issue('model_reported_unresolved')
    if raw.get('image_discrepancies') != []:
        issue('image_ocr_discrepancy')
        sheet['image_discrepancies'] = deepcopy(raw.get('image_discrepancies'))
    if not sheet['unresolved']:
        sheet['validation_status'] = 'source_validated'
    _knowledge_fields(raw, sheet, [text], language, issue)
    _link_calculation_inputs(sheet)
    _calculation_steps(raw, sheet, text, language, issue)
    if sheet['unresolved']:
        sheet['validation_status'] = 'unresolved'
    if sheet['semantic_status'] == 'missing':
        sheet['diagnostics'].append('calculation_semantics_missing')
    sheet['render_markdown'] = _render(sheet['sections'], language)
    return sheet



def _knowledge_fields(raw, result, quotes, language, issue):
    """Separate generated meaning from verbatim engineering facts."""
    description = raw.get('semantic_desc', '')
    valid = valid_description(description, result.get('name', '')) if isinstance(description, str) else ''
    if valid == result.get('latex') or description_mismatch(valid, language):
        valid = ''
    result['semantic_desc'] = valid
    result['semantic_status'] = 'model_proposed' if valid else 'missing'
    if not valid and description:
        result.setdefault('rejected_fields', []).append({'field': 'semantic_desc', 'candidate': deepcopy(description),
                                                        'reason': 'semantic_description_invalid'})
    # Relations reference exact symbols present in this item's evidence; no guessed variables.
    for key in ('inputs', 'output'):
        if key not in raw:
            continue
        values = raw[key] if key == 'inputs' else [raw[key]]
        valid_values = []
        if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() and any(v in q for q in quotes) for v in values):
            issue('field_source_mismatch')
            result.setdefault('rejected_fields', []).append({'field': key, 'candidate': deepcopy(raw[key]),
                                                            'reason': 'field_source_mismatch'})
        else:
            valid_values = list(dict.fromkeys(values))
        result[key] = valid_values if key == 'inputs' else (valid_values[0] if valid_values else '')


def _link_calculation_inputs(sheet):
    """Resolve local symbol dependencies without merging pages or guessing definitions."""
    items = [entry for section in sheet['sections'] for entry in section['items']]
    definitions = {}
    for entry in items:
        symbol = entry.get('output') or (entry.get('symbol') if entry['kind'] == 'input' else '')
        if symbol:
            definitions.setdefault(symbol, []).append(entry['id'])
    for entry in items:
        if 'inputs' not in entry:
            continue
        entry['depends_on'] = []
        entry['unresolved_inputs'] = []
        for symbol in entry['inputs']:
            matches = [identifier for identifier in definitions.get(symbol, []) if identifier != entry['id']]
            if len(matches) == 1:
                if matches[0] not in entry['depends_on']:
                    entry['depends_on'].append(matches[0])
            else:
                entry['unresolved_inputs'].append(symbol)
    sheet['semantic_status'] = ('model_proposed' if sheet.get('semantic_desc') and all(
        entry.get('semantic_desc') for entry in items if entry['kind'] in {'formula', 'branch', 'check'}) else 'missing')


def _calculation_steps(raw, sheet, text, language, issue):
    if 'steps' not in raw:
        return
    sheet['steps'] = []
    steps = raw['steps']
    if not isinstance(steps, list) or len(steps) > 100:
        issue('calculation_steps_invalid')
        return
    known = {entry['id']: entry for section in sheet['sections'] for entry in section['items']}
    for step in steps:
        try:
            if not isinstance(step, dict) or not isinstance(step.get('title'), str) or not step['title'].strip():
                raise ValueError('calculation_steps_invalid')
            refs = step.get('item_ids')
            if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in known for ref in refs):
                raise ValueError('calculation_step_reference_invalid')
            quotes = step.get('sources')
            if not isinstance(quotes, list) or not quotes:
                raise ValueError('invalid_source_reference')
            ranges = _source_ranges(text, quotes, step.get('source_ranges'))
            # Evidence for a step must actually overlap the referenced calculation items.
            if any(not any(a < end and start < b for start, end in known[ref]['source']['text_ranges']
                           for a, b in ranges) for ref in refs):
                raise ValueError('calculation_step_reference_invalid')
            result = {'title': step['title'], 'item_ids': list(dict.fromkeys(refs)),
                      'source': {'sha256': sheet['source_sha256'], 'text_ranges': ranges}}
            _knowledge_fields(step, result, quotes, language, issue)
            sheet['steps'].append(result)
        except ValueError as exc:
            issue(str(exc))
            sheet.setdefault('rejected_steps', []).append({'reason': str(exc), 'candidate': deepcopy(step)})

def classification_failed(item, reason, content=None):
    """Failed automatic classification cannot silently become a queryable legacy table."""
    if item.get('table_kind_source') == 'manual':
        return
    apply_calculation_sheet(item, {'table_kind': 'uncertain', 'classification_evidence': []},
                            content if content is not None else str(item.get('raw_html') or item.get('markdown') or ''))
    item['table_classification']['reason'] = reason
    item.pop('calculation_sheet', None)
    item.pop('content_format', None)


def table_content_quality(items):
    reviews = [{'index': i, 'layout_id': item.get('layout_id'), 'table_kind': item['table_kind'],
                'status': 'needs_review',
                'reason': ('calculation_sheet_requires_image_review' if item['table_kind'] == 'calculation_sheet'
                           else 'table_type_requires_review')}
               for i, item in enumerate(items) if item.get('table_kind', 'data_table') != 'data_table']
    return {'complete': not reviews, 'objects': reviews}


def extract_calculation_items(vlm, image_path, item, content, object_ref):
    """One dedicated image call, with echoed identity/hash and no local retry."""
    ctx = source_context(content)
    ctx['description_language'] = getattr(vlm, 'description_language', 'unknown')
    target = {'object_ref': object_ref, 'source_sha256': ctx.get('sha256'),
              'calculation_source': ctx,
              **{key: item[key] for key in ('layout_id', 'bbox', 'bbox_space') if key in item}}
    reason = None
    try:
        response = vlm.extract_calculation_sheet(image_path, target)
        if (not isinstance(response, dict) or response.get('object_ref') != object_ref
                or response.get('source_sha256') != ctx.get('sha256')):
            reason = 'calculation_identity_mismatch'
        elif getattr(vlm, 'last_call_info', {}).get('finish_reason') in {'length', 'content_filter', 'tool_calls'}:
            reason = 'calculation_response_incomplete'
        else:
            item['calculation_sheet'] = parse_calculation_sheet(response, ctx, item)
            if item['calculation_sheet'].get('semantic_desc'):
                item['semantic_desc'] = item['calculation_sheet']['semantic_desc']
                item['description'] = item['semantic_desc']
    except Exception:
        reason = 'calculation_provider_failed'
    if reason:
        item['calculation_sheet'] = parse_calculation_sheet(None, ctx, item)
        item['calculation_sheet']['unresolved'] = [{'reason': reason}]


def needs_calculation_call(item):
    return (item.get('table_kind') == 'calculation_sheet'
            and item.get('calculation_sheet', {}).get('validation_status') != 'source_validated')


def calculation_budget(vlm):
    value = getattr(vlm, 'table_analysis_max_model_calls', 2)
    return value if type(value) is int and 0 <= value <= 8 else 0


def complete_calculation_batch(vlm, image_path, targets, used_calls):
    """Share one analysis budget across all tables, including the classification call."""
    additional = 0
    for item, content, object_ref in targets:
        if not needs_calculation_call(item):
            continue
        if used_calls + additional >= calculation_budget(vlm):
            item['calculation_sheet']['unresolved'] = [{'reason': 'table_analysis_budget_exhausted'}]
        elif not callable(getattr(vlm, 'extract_calculation_sheet', None)):
            item['calculation_sheet']['unresolved'] = [{'reason': 'calculation_provider_unavailable'}]
        else:
            additional += 1
            extract_calculation_items(vlm, image_path, item, content, object_ref)
    return additional
