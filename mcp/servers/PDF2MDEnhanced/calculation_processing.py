"""Bounded, identity-scoped processing behind the existing table extraction tool."""
from .calculation_input import math_spans
from copy import deepcopy
import re

from .calculation_sheet import (
    apply_calculation_sheet, calculation_budget, parse_calculation_sheet, source_context,
    PhysicalRequestBudgetExceeded, calculation_source_sections, repair_table_classification,
)


CONTINUATION_MARKER = r"(?:[（(](?:cont(?:inued|inue|[’']?d)?\.?|续表|续)[）)]|(?:continued|continue|cont[’']d|cont)\b|续表|续)"

IDENTITY_KEYS = {'tenant_id', 'doc_id', 'version', 'page_no', 'table_pk', 'layout_id', 'source_sha256'}


def valid_identity(identity):
    return (isinstance(identity, dict) and set(identity) == IDENTITY_KEYS
            and all(isinstance(identity.get(k), str) and 0 < len(identity[k]) <= 256
                    for k in ('tenant_id', 'doc_id', 'table_pk', 'layout_id'))
            and all(type(identity.get(k)) is int and identity[k] > 0 for k in ('version', 'page_no'))
            and isinstance(identity.get('source_sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', identity['source_sha256']) is not None)


def validate_request(request, hint, mode):
    if hint not in ('auto', 'data_table', 'calculation_sheet') or mode not in ('auto', 'organize_existing', 'reextract'):
        raise ValueError('invalid_calculation_processing_mode')
    if mode != 'auto' and hint == 'auto':
        raise ValueError('manual_table_kind_required')
    if not isinstance(request, dict) or not valid_identity(request.get('identity')):
        raise ValueError('calculation_identity_mismatch')
    if request.get('stage') is not None and (request['stage'] != 'transcription'
            or mode == 'organize_existing' or hint == 'data_table'):
        raise ValueError('invalid_calculation_processing_stage')
    content = request.get('existing_content', '')
    if not isinstance(content, str) or len(content) > 100000:
        raise ValueError('input_budget_exceeded')
    if mode == 'organize_existing' and not content.strip():
        raise ValueError('existing_content_required')
    adjacent = request.get('adjacent_objects', [])
    if not isinstance(adjacent, list) or len(adjacent) > 2:
        raise ValueError('adjacent_context_invalid')
    identity = request['identity']; pages = set()
    for obj in adjacent:
        other = obj.get('identity') if isinstance(obj, dict) else None
        if (not valid_identity(other)
                or any(identity[k] != other[k] for k in ('tenant_id', 'doc_id', 'version', 'source_sha256'))
                or abs(identity['page_no'] - other['page_no']) != 1
                or other['page_no'] in pages or other['table_pk'] == identity['table_pk']
                or other['layout_id'] == identity['layout_id']
                or not isinstance(obj.get('source_text'), str) or len(obj['source_text']) > 100000):
            raise ValueError('adjacent_context_invalid')
        pages.add(other['page_no'])


def initial_item(request, hint, mode):
    identity = request.get('identity', {}) if isinstance(request, dict) else {}
    item = {'table_kind': hint if hint != 'auto' else 'uncertain',
            'table_kind_source': 'manual' if hint != 'auto' else 'automatic',
            'processing_mode': mode, 'manualReviewRequired': True, 'degraded': True,
            'lookup_status': 'unavailable', 'lookup_sections': [],
            'continuation': {'status': 'pending', 'reason': 'classification_not_run'}}
    if valid_identity(identity):
        item.update(calculation_identity=deepcopy(identity), layout_id=identity['layout_id'])
    if isinstance(request, dict) and isinstance(request.get('existing_content'), str):
        item['existing_content'] = request['existing_content']
    if hint == 'calculation_sheet':
        item['content_format'] = 'calculation_sheet_json'
    return item


def result_for(item, calls=0, reason=None):
    # Results are reviewable proposals, never publication or image-accuracy claims.
    result = {'tool': 'extract_page_tables', 'status': 'failed' if reason else 'needs_review',
              'items': [item], 'tables': [item], 'model_calls': {'glm_ocr': 0, 'vlm_ocr': calls},
              'budget': {'logical_calls': calls, 'transport_retries_included': False},
              'warnings': [reason] if reason else [],
              'table_content_quality': {'complete': False, 'objects': [{
                  'layout_id': item.get('layout_id'), 'status': 'needs_review',
                  'reason': reason or 'calculation_proposal_requires_review'}]}}
    if reason:
        item['reason'] = reason
        result['reason'] = reason
    result.update({k: deepcopy(v) for k, v in item.items() if k not in ('reason',)})
    return result


RESPONSE_CODES = {
    'calculation_ocr_unavailable', 'calculation_ocr_single_image_required',
    'calculation_identity_mismatch', 'calculation_source_missing', 'calculation_source_rewritten',
    'calculation_source_revision_mismatch', 'calculation_response_invalid', 'calculation_response_empty',
    'calculation_response_truncated', 'calculation_response_filtered', 'calculation_response_incomplete',
    'calculation_transcription_missing', 'calculation_transcription_empty',
    'calculation_transcription_invalid_type', 'calculation_transcription_too_long',
}


def response_error(vlm):
    return {'length': 'calculation_response_truncated', 'content_filter': 'calculation_response_filtered',
            'tool_calls': 'calculation_response_incomplete'}.get(
                getattr(vlm, 'last_call_info', {}).get('finish_reason'))


def transcription_text(response):
    if not isinstance(response, dict):
        raise ValueError('calculation_response_invalid')
    if 'source_text' not in response:
        raise ValueError('calculation_transcription_missing')
    text = response['source_text']
    if not isinstance(text, str):
        raise ValueError('calculation_transcription_invalid_type')
    if not text.strip():
        raise ValueError('calculation_transcription_empty')
    if len(text) > 100000:
        raise ValueError('calculation_transcription_too_long')
    return text


def transcription_body(text, caption):
    """Separate an exact duplicated leading caption; retain original image text independently."""
    if not isinstance(caption, str) or not caption.strip():
        return text
    expected = ' '.join(caption.split())
    prefix = ''
    for line in text.splitlines(keepends=True):
        prefix += line
        if ' '.join(prefix.split()) == expected:
            remaining = text[len(prefix):].lstrip('\r\n')
            return remaining if remaining.strip() else text
        if len(' '.join(prefix.split())) >= len(expected):
            break
    return text


def source_batches(sections, context_size=0):
    """Bound semantic input at whole-unit boundaries; never split a formula."""
    leading = []
    for section in sections:
        if section['items']:
            break
        leading.append(section)
    heading_size = context_size + sum(len(s['title']) for s in leading)
    batches = []
    batch = deepcopy(leading)
    size, count = heading_size, 0
    for section in sections[len(leading):]:
        group = None
        for unit in section['items'] or [None]:
            length = len(section['title']) + (len(unit['text']) + sum(len(c['text']) for c in unit.get('row_context', [])) if unit else 0)
            if count and (size + length > 12000 or count >= 40):
                batches.append(batch); batch = deepcopy(leading); size, count = heading_size, 0; group = None
            if group is None:
                group = {**section, 'items': []}
                batch.append(group)
            if unit:
                group['items'].append(unit)
                count += 1
            size += length
    if batch:
        batches.append(batch)
    return batches


def structure_calculation_source(vlm, item, content, target, available_calls, resume=None, identity=None, automatic=False):
    """Common text-only semantic stage for saved content and existing OCR."""
    source = item.setdefault('calculation_source', {})
    original_content = content
    original_context = source_context(content)
    if source.get('origin') == 'image_transcription':
        content = transcription_body(content, source.get('table_title'))
    # OCR-generated math wrappers are presentation syntax, not formula characters.
    # Keep the untouched image_transcription and repair only a provably redundant final dollar.
    if source.get('origin') == 'image_transcription' and content.endswith('$$'):
        spans = math_spans(content)
        candidate = content[:-1]
        if (spans and not spans[-1][2] and content[spans[-1][0]:].startswith('$')
                and not content[spans[-1][0]:].startswith('$$')
                and all(complete for _, _, complete in math_spans(candidate))):
            content = candidate
            source['transcription_normalizations'] = ['redundant_trailing_math_delimiter']
    ctx = source_context(content, structural=True)
    # Parsing text may be normalized; identity always belongs to the saved source.
    for key in ('sha256', 'source_revision'):
        if key in original_context:
            ctx[key] = original_context[key]
    ctx['description_language'] = getattr(vlm, 'description_language', 'unknown')
    source.update({**ctx, 'original_content': original_content})
    pipeline = source.setdefault('pipeline', {})
    pipeline['provider'] = getattr(vlm, 'provider', '')
    pipeline['model'] = getattr(vlm, 'model', '')
    pipeline['request_timeout_sec'] = getattr(vlm, 'timeout_sec', None)
    pipeline['max_tokens'] = getattr(vlm, 'max_tokens', None)
    pipeline['framing'] = {'status': 'failed', 'source_revision': ctx.get('source_revision')}
    item.pop('calculation_sheet', None)
    if not ctx['text'].strip():
        return 0, 'calculation_source_missing'
    try:
        ctx['source_sections'] = calculation_source_sections(ctx['text'], ctx.get('table_rows'))
    except ValueError:
        pipeline['framing']['reason'] = 'calculation_framing_failed'
        return 0, 'input_budget_exceeded'
    first_section = ctx['source_sections'][0] if ctx['source_sections'] else {}
    preamble = first_section.get('items', []) if not first_section.get('title') else []
    ctx['document_preamble'] = []
    if preamble and all(not u['math'] and not re.search(r'[=<>≤≥]', u['text']) for u in preamble):
        start, end = preamble[0]['source_range'][0], preamble[-1]['source_range'][1]
        ctx['document_preamble'] = [{'text': ctx['text'][start:end], 'source_range': [start, end]}]
    total = sum(len(s['items']) for s in ctx['source_sections'])
    pipeline['framing'].update(status='complete', input_units=total, output_units=total)
    invalid_units = [u for section in ctx['source_sections'] for u in section['items']
                     if any(not complete for _, _, complete in math_spans(u['text']))
                     or any(re.match(r'^[_^]', value) for value in u['math'])]
    invalid_ids = {u['id'] for u in invalid_units}
    eligible = [{**section, 'items': [u for u in section['items'] if u['id'] not in invalid_ids]}
                for section in ctx['source_sections']]
    batches = source_batches([section for section in eligible if section['items'] or not invalid_units],
                             sum(len(u['text']) for u in ctx['document_preamble']))
    if automatic:
        available_calls = len(batches)
        vlm.reserve_automatic_calculation_calls(available_calls)
    if invalid_units:
        pipeline['framing'].update(status='needs_review', reason='calculation_source_math_invalid',
                                   invalid_units=len(invalid_units))
    combined = {'sections': [], 'unresolved': [], 'image_discrepancies': [],
                'source_revision': ctx['source_revision']}
    descriptions = []
    errors = ['calculation_source_math_invalid'] if invalid_units else []
    identity = identity or {k: target.get(k) for k in ('object_ref', 'source_sha256')}
    progress = [{'id': index + 1, 'source_item_ids': [u['id'] for s in batch for u in s['items']],
                 'status': 'pending'} for index, batch in enumerate(batches)]
    previous = {}
    if resume is not None:
        if (not isinstance(resume, dict) or resume.get('source_revision') != ctx['source_revision']
                or resume.get('identity') != identity or not isinstance(resume.get('batches'), list)
                or len(resume['batches']) != len(progress)):
            return 0, 'calculation_resume_mismatch'
        for expected, saved in zip(progress, resume['batches']):
            if (not isinstance(saved, dict) or saved.get('id') != expected['id']
                    or saved.get('source_item_ids') != expected['source_item_ids']
                    or saved.get('status') not in ('pending', 'complete', 'partial', 'failed')):
                return 0, 'calculation_resume_mismatch'
            if saved['status'] == 'complete':
                if not isinstance(saved.get('result'), dict):
                    return 0, 'calculation_resume_mismatch'
                previous[expected['id']] = saved['result']
    planned_calls = min(available_calls, sum(p['id'] not in previous for p in progress))
    if planned_calls > 0 and callable(getattr(vlm, 'calculation_work_started', None)):
        vlm.calculation_work_started(planned_calls)
    calls = 0
    for batch, checkpoint in zip(batches, progress):
        cached = previous.get(checkpoint['id'])
        code = None
        if cached is None and calls >= available_calls:
            code = 'table_analysis_budget_exhausted'
        elif cached is None and getattr(vlm, 'physical_request_limit', None) is not None and vlm.physical_requests >= vlm.physical_request_limit:
            code = 'table_analysis_physical_budget_exhausted'
        if code:
            errors.append(code)
            checkpoint['reason'] = code
            continue
        # Only a batch's citation text is sent. Ranges remain relative to the complete revision.
        batch_text = ctx['text'] if len(batches) == 1 else '\n'.join(
            value for s in batch for value in [s['title'], *[part['text'] for u in s['items'] for part in [u, *u.get('row_context', [])]]] if value)
        if len(batch_text) > 12000:
            errors.append('calculation_unit_budget_exceeded')
            checkpoint.update(status='failed', reason='calculation_unit_budget_exceeded')
            continue
        batch_target = {**target, 'calculation_stage': 'semantic', 'source_text': batch_text,
                        'source_revision': ctx['source_revision'], 'source_sections': batch,
                        'document_preamble': ctx['document_preamble'], 'range_unit': 'unicode_codepoint'}
        caption = source.get('table_title') or item.get('table_title') or item.get('tableTitle')
        if isinstance(caption, str) and caption.strip():
            batch_target['table_title'] = caption
            source['table_title'] = caption
        batch_target.pop('existing_content', None)
        batch_target.pop('calculation_source', None)
        batch_target.pop('adjacent_objects', None)
        try:
            if cached is None:
                calls += 1
                raw = vlm.extract_calculation_sheet(None, batch_target)
                code = response_error(vlm)
                if code:
                    raise ValueError(code)
            else:
                raw = deepcopy(cached)
            if not isinstance(raw, dict):
                raise ValueError('calculation_response_invalid')
            if raw.get('object_ref') != target['object_ref'] or raw.get('source_sha256') != target['source_sha256']:
                raise ValueError('calculation_identity_mismatch')
            if raw.get('source_revision', ctx['source_revision']) != ctx['source_revision']:
                raise ValueError('calculation_source_revision_mismatch')
            if raw.get('source_text', batch_text) != batch_text:
                raise ValueError('calculation_source_rewritten')
            if not isinstance(raw.get('sections'), list):
                raise ValueError('calculation_response_invalid')
            allowed = {u['id'] for s in batch for u in s['items']}
            for section in raw['sections']:
                for entry in section.get('items', []) if isinstance(section, dict) and isinstance(section.get('items'), list) else []:
                    if isinstance(entry, dict):
                        entry.pop('bbox', None)
                        if ('source_item_id' in entry and (not isinstance(entry['source_item_id'], str) or entry['source_item_id'] not in allowed)
                                or 'source_item_ids' in entry and (not isinstance(entry['source_item_ids'], list)
                                or not all(isinstance(k, str) and k in allowed for k in entry['source_item_ids']))):
                            entry['source_item_id'] = 'invalid-batch-source-id'
            batch_sheet = parse_calculation_sheet(raw, {**ctx, 'source_sections': batch}, item)
            # Absolute source ranges still reference the whole text. Other batches
            # are intentionally unmapped here; framed coverage checks every local unit.
            batch_issues = [issue for issue in batch_sheet['unresolved']
                            if issue.get('reason') != 'unmapped_source_text']
            batch_complete = (not batch_issues and raw.get('unresolved') == []
                              and raw.get('image_discrepancies') == []
                              and batch_sheet.get('semantic_status') != 'missing'
                              and batch_sheet['coverage']['needs_review'] == 0)
            checkpoint['status'] = 'complete' if batch_complete else 'partial'
            if batch_complete:
                checkpoint['result'] = {key: deepcopy(raw[key]) for key in (
                    'object_ref', 'source_sha256', 'source_revision', 'sections', 'semantic_desc',
                    'unresolved', 'image_discrepancies', 'inputs', 'output', 'steps') if key in raw}
            combined['sections'].extend(raw['sections'])
            for field in ('unresolved', 'image_discrepancies'):
                if raw.get(field) != []:
                    combined[field].append({'reason': 'model_reported_unresolved'})
            if isinstance(raw.get('semantic_desc'), str) and raw['semantic_desc'].strip():
                descriptions.append(raw['semantic_desc'])
            if len(batches) == 1:
                for key in ('inputs', 'output', 'steps'):
                    if key in raw:
                        combined[key] = raw[key]
        except PhysicalRequestBudgetExceeded:
            errors.append('table_analysis_physical_budget_exhausted')
            checkpoint.update(status='failed', reason=errors[-1])
        except TimeoutError:
            errors.append('calculation_provider_timeout')
            checkpoint.update(status='failed', reason=errors[-1])
        except Exception as exc:
            errors.append(str(exc) if isinstance(exc, ValueError) and str(exc) in RESPONSE_CODES
                          else 'calculation_provider_failed')
            checkpoint.update(status='failed', reason=errors[-1])
    combined['semantic_desc'] = '\n'.join(descriptions)
    sheet = parse_calculation_sheet(combined, ctx, item)
    for unit in invalid_units:
        sheet['unresolved'].append({'reason': 'calculation_source_math_invalid',
                                    'source_item_id': unit['id'], 'source_range': unit['source_range']})
    for code in dict.fromkeys(errors):
        sheet['unresolved'].append({'reason': code})
    if errors:
        sheet['validation_status'] = 'unresolved'
    if not batches or len(descriptions) != len(batches):
        sheet['semantic_status'] = 'missing'
    item['calculation_sheet'] = sheet
    item['content_format'] = 'calculation_sheet_json'
    if sheet.get('semantic_desc'):
        item['semantic_desc'] = sheet['semantic_desc']
    complete = (not errors and not sheet['unresolved'] and sheet['semantic_status'] != 'missing'
                and sheet['coverage']['needs_review'] == 0 and total > 0)
    pipeline['semantic'] = {'status': 'complete' if complete else 'partial',
                            'reason': None if complete else (errors[0] if errors else 'calculation_semantic_partial'),
                            'input_units': total, 'output_units': sheet['coverage']['structured'],
                            'logical_calls': calls, 'batch_count': len(batches),
                            'source_revision': ctx['source_revision'], 'identity': deepcopy(identity), 'batches': progress}
    pipeline['validation'] = {'status': 'complete' if complete else 'needs_review', **sheet['coverage']}
    if getattr(vlm, 'physical_request_limit', None) is not None:
        pipeline['physical_requests'] = vlm.physical_requests
        pipeline['physical_request_limit'] = vlm.physical_request_limit
    # Preserve failure envelopes for text-only callers while retaining a recovery draft inside them.
    return calls, errors[0] if errors and not combined['sections'] else None


def _read_response(item, response, identity, hint, mode, language):
    if not isinstance(response, dict):
        raise ValueError('calculation_response_invalid')
    if (response.get('object_ref') != identity['layout_id']
            or response.get('source_sha256') != identity['source_sha256']):
        raise ValueError('calculation_identity_mismatch')
    content = item.get('existing_content', '') if mode == 'organize_existing' else transcription_text(response)
    if not isinstance(content, str) or not content.strip() or len(content) > 100000:
        raise ValueError('calculation_source_missing')
    original_transcription = content
    ctx = source_context(content); ctx['description_language'] = language
    if mode == 'organize_existing' and response.get('source_text') != ctx['text']:
        raise ValueError('calculation_source_rewritten')
    if mode == 'organize_existing':
        if hint == 'calculation_sheet':
            ctx['source_sections'] = calculation_source_sections(ctx['text'], ctx.get('table_rows'))
        response = deepcopy(response)
        for section in response.get('sections', []) if isinstance(response.get('sections'), list) else []:
            if not isinstance(section, dict) or not isinstance(section.get('items'), list):
                continue
            for entry in section['items']:
                if isinstance(entry, dict):
                    entry.pop('bbox', None)
    if hint == 'auto':
        apply_calculation_sheet(item, {**response, 'calculation_sheet': response}, content, language)
    else:
        item['table_classification'] = {'kind': hint, 'status': 'manual_confirmed',
                                        'reason': 'manual_type_constraint', 'evidence': []}
        if hint == 'calculation_sheet':
            item['calculation_sheet'] = parse_calculation_sheet(response, ctx, item)
    # Keep image transcription separate from the full-document identity hash.
    item['calculation_source'] = {key: value for key, value in ctx.items() if key != 'source_sections'}
    item['calculation_source']['original_content'] = content
    if mode != 'organize_existing':
        item['calculation_source']['origin'] = 'image_transcription'
        item['calculation_source']['image_transcription'] = original_transcription
    else:
        item['calculation_source']['origin'] = 'existing_content'
        item['calculation_source']['original_content'] = content
        for section in item.get('calculation_sheet', {}).get('sections', []):
            for entry in section['items']:
                entry['source']['location_scope'] = 'source_text'
    if item['table_kind'] == 'calculation_sheet':
        if item['calculation_sheet'].get('semantic_desc'):
            item['semantic_desc'] = item['calculation_sheet']['semantic_desc']
        item['content_format'] = 'calculation_sheet_json'
    else:
        item.pop('calculation_sheet', None)
        item.pop('content_format', None)
    if item['table_kind'] == 'data_table':
        # Normal data tables use the caller's existing normalization path.
        item['markdown'] = content
    item['table_kind_source'] = 'automatic' if hint == 'auto' else 'manual'
    return content


def _table_number(text):
    numbers = set(re.findall(r'(?:\bTable|表)\s*(\d+(?:[.\-]\d+)+)', text, re.I))
    return next(iter(numbers)) if len(numbers) == 1 else None


def _continuation(raw, identity, content, known):
    if not isinstance(raw, dict) or raw.get('status') not in ('none', 'pending', 'conflict', 'proposed'):
        return {'status': 'pending', 'reason': 'adjacent_context_required'}
    status = raw['status']
    if status != 'proposed':
        return {'status': status, 'reason': {'none': 'no_continuation_evidence',
                'pending': 'adjacent_context_required', 'conflict': 'continuation_evidence_conflict'}[status]}
    predecessor = raw.get('predecessor')
    matches = [obj for obj in known if obj['identity'] == predecessor]
    if len(matches) != 1 or predecessor['page_no'] != identity['page_no'] - 1:
        return {'status': 'conflict', 'reason': 'continuation_identity_mismatch'}
    other = matches[0]
    number = _table_number(content)
    if not number or number != _table_number(other['source_text']):
        return {'status': 'conflict', 'reason': 'continuation_evidence_conflict'}
    if other.get('table_kind') != 'calculation_sheet':
        return {'status': 'pending', 'reason': 'adjacent_classification_unresolved'}
    return {'status': 'proposed', 'reason': 'same_table_continuation_proposed',
            'predecessor': deepcopy(predecessor)}


def title_continuation(identity, content, known):
    """Resolve an explicit title continuation through the existing scoped proposal contract."""
    def compact(text):
        return re.sub(r'\s+', ' ', re.sub(r'[#*]', '', text)).strip().casefold()

    marker = CONTINUATION_MARKER
    matches = []
    current = compact(content)
    for obj in known:
        previous = obj.get('identity', {})
        title = obj.get('table_title')
        if (not valid_identity(previous) or obj.get('table_kind') != 'calculation_sheet'
                or previous['page_no'] != identity['page_no'] - 1
                or any(previous[k] != identity[k] for k in ('tenant_id', 'doc_id', 'version', 'source_sha256'))
                or not isinstance(title, str) or not title.strip()):
            continue
        base = re.sub(marker + r'$', '', compact(title)).strip()
        if not base or not current.startswith(base):
            continue
        if re.match(marker, current[len(base):].lstrip()):
            matches.append(obj)
    if len(matches) != 1:
        return None
    return _continuation({'status': 'proposed', 'predecessor': matches[0]['identity']}, identity, content, matches)


def process_request(request, hint, mode, vlm, image_path=None, adjacent_images=None, transcribe=None):
    """Transcribe/classify, optionally review neighbors, then structure within one budget."""
    item = initial_item(request, hint, mode)
    calls = 0
    structured = False
    ocr_calls = 0
    transcription_only = isinstance(request, dict) and request.get('stage') == 'transcription'
    def finish(reason=None):
        nonlocal calls, structured
        if not reason and transcription_only and item.get('table_kind') == 'calculation_sheet':
            item.pop('calculation_sheet', None)
            item.setdefault('calculation_source', {}).setdefault('pipeline', {})['semantic'] = {
                'status': 'pending', 'reason': 'source_persistence_required', 'logical_calls': 0}
        if not reason and not transcription_only and not structured and item.get('table_kind') == 'calculation_sheet' and item.get('calculation_source', {}).get('text'):
            structured = True
            extra, stage_reason = structure_calculation_source(vlm, item, item['calculation_source']['original_content'], target, calculation_budget(vlm) - calls, identity=identity)
            calls += extra
            if 'calculation_sheet' not in item:
                reason = stage_reason
        if reason and mode != 'organize_existing' and calls and not item.get('calculation_source', {}).get('text'):
            item.setdefault('calculation_source', {})['pipeline'] = {
                'transcription': {'status': 'failed', 'reason': reason, 'logical_calls': calls},
                'provider': getattr(vlm, 'provider', ''), 'model': getattr(vlm, 'model', '')}
        result = result_for(item, calls, reason)
        result["model_calls"] = {"glm_ocr": ocr_calls, "vlm_ocr": calls - ocr_calls}
        if getattr(vlm, 'physical_request_limit', None) is not None:
            result['budget'].update(physical_requests=vlm.physical_requests,
                                     physical_request_limit=vlm.physical_request_limit, sdk_retries=0)
        return result
    try:
        validate_request(request, hint, mode)
        identity = request['identity']
        title = request.get('table_title')
        if isinstance(title, str) and title.strip() and len(title) <= 500:
            item['table_title'] = title.strip()
        if getattr(vlm, 'physical_request_limit', None) == 0:
            return finish('table_analysis_physical_budget_exhausted')
        if calculation_budget(vlm) == 0:
            return finish('table_analysis_budget_exhausted')
        target = {'object_ref': identity['layout_id'], 'source_sha256': identity['source_sha256'],
                  'processing_mode': mode, 'table_kind_hint': hint,
                  'existing_content': request.get('existing_content', '')}
        if mode != 'organize_existing' and hint != 'data_table':
            target['calculation_stage'] = 'transcription' if hint == 'calculation_sheet' else 'classification_transcription'
            target.pop('existing_content', None)
        if mode == 'organize_existing':
            target['source_text'] = source_context(request['existing_content'])['text']
            if hint == 'calculation_sheet':
                target['source_sections'] = calculation_source_sections(target['source_text'])
            if not target['source_text'].strip():
                return finish('calculation_source_missing')
        if mode != 'organize_existing' and not image_path:
            return finish('source_image_unavailable')
        if mode == 'organize_existing' and hint == 'calculation_sheet':
            structured = True
            item['table_classification'] = {'kind': hint, 'status': 'manual_confirmed',
                                            'reason': 'manual_type_constraint', 'evidence': []}
            item['calculation_source'] = {'origin': 'existing_content'}
            item['continuation'] = {'status': 'none', 'reason': 'not_assessed_text_only'}
            source_title = source_context(request['existing_content']).get('title')
            if source_title:
                item['table_title'] = item['tableTitle'] = source_title
                item['calculation_source']['table_title'] = source_title
                fragment = bool(re.search(CONTINUATION_MARKER, source_title, re.IGNORECASE))
                item['continuation'] = {'status': 'pending' if fragment else 'none',
                                        'reason': 'adjacent_context_required' if fragment else 'no_continuation_evidence'}
            calls, reason = structure_calculation_source(vlm, item, request['existing_content'], target, calculation_budget(vlm),
                                                         request.get('calculation_resume'), identity)
            return finish(reason)
        calls += 1
        if transcribe is not None and mode != 'organize_existing' and hint != 'data_table':
            ocr_calls += 1
            response = transcribe(image_path, target)
        else:
            response = vlm.extract_calculation_sheet(image_path, target)
        if response_error(vlm):
            return finish(response_error(vlm))
        content = _read_response(item, response, identity, hint, mode, getattr(vlm, 'description_language', 'unknown'))
        if hint == 'auto':
            calls += repair_table_classification(vlm, image_path, item, content, identity['layout_id'],
                                                 calculation_budget(vlm) - calls)
        item['calculation_source']['pipeline'] = {'transcription': {'status': 'complete',
            'engine': 'ocr' if ocr_calls else 'vlm', 'logical_calls': 1}}
        title = response.get('table_title') or request.get('table_title')
        if isinstance(title, str) and title.strip() and len(title) <= 500:
            item['table_title'] = title.strip()
            item['tableTitle'] = title.strip()
            item['calculation_source']['table_title'] = title.strip()

        if mode == 'organize_existing':
            item['continuation'] = {'status': 'none', 'reason': 'not_assessed_text_only'}
            return finish()
        if item['table_kind'] == 'calculation_sheet':
            linked = title_continuation(identity, item.get('table_title') or content, request.get('adjacent_objects', []))
            if linked and linked['status'] == 'proposed':
                item['continuation'] = linked
                return finish()
        raw_continuation = response.get('continuation')
        if raw_continuation is None:
            raw_continuation = {'status': 'pending' if re.search(
                CONTINUATION_MARKER, item.get('table_title', ''), re.IGNORECASE) else 'none'}
        if transcription_only:
            item['continuation'] = _continuation(raw_continuation, identity, content, request.get('adjacent_objects', []))
            return finish()
        needs_context = (item['table_kind'] == 'uncertain' or response.get('continuation_required') is True
                         or isinstance(raw_continuation, dict) and raw_continuation.get('status') in ('pending', 'proposed'))
        adjacent = request.get('adjacent_objects', [])
        if not needs_context:
            item['continuation'] = _continuation(raw_continuation, identity, content, [])
            return finish()
        item['continuation'] = {'status': 'pending', 'reason': 'adjacent_context_required'}
        # Once the current object is a calculation sheet, reserve the remaining
        # budget for its semantics. An unresolved relationship is independent.
        if item['table_kind'] == 'calculation_sheet' or not adjacent:
            return finish()
        if calls >= calculation_budget(vlm):
            item['continuation']['reason'] = 'table_analysis_budget_exhausted'
            return finish()
        if not adjacent_images or len(adjacent_images) != len(adjacent):
            item['continuation']['reason'] = 'source_image_unavailable'
            return finish()
        # Previous object first. Request image ordering must match this ordering.
        ordered = sorted(zip(adjacent, adjacent_images), key=lambda pair: pair[0]['identity']['page_no'])
        target['adjacent_objects'] = [{k: obj[k] for k in ('identity', 'source_text')} for obj, _ in ordered]
        calls += 1
        response = vlm.extract_calculation_sheet([image_path, *[path for _, path in ordered]], target)
        if response_error(vlm):
            return finish(response_error(vlm))
        content = _read_response(item, response, identity, hint, mode, getattr(vlm, 'description_language', 'unknown'))
        item['calculation_source']['pipeline'] = {'transcription': {'status': 'complete', 'logical_calls': calls}}
        title = response.get('table_title') or request.get('table_title')
        if isinstance(title, str) and title.strip() and len(title) <= 500:
            item['table_title'] = title.strip()
            item['tableTitle'] = title.strip()
            item['calculation_source']['table_title'] = title.strip()

        reviews = response.get('reviewed_objects', [])
        if not isinstance(reviews, list) or len(reviews) > len(adjacent):
            return finish('continuation_identity_mismatch')
        known = []; reviewed = []
        for obj in adjacent:
            matches = [r for r in reviews if isinstance(r, dict) and r.get('identity') == obj['identity']]
            if len(matches) > 1:
                return finish('continuation_identity_mismatch')
            if len(matches) != 1:
                continue
            classified = {}
            apply_calculation_sheet(classified, matches[0], obj['source_text'])
            known.append({**obj, 'table_kind': classified.get('table_kind')})
            reviewed.append({'identity': deepcopy(obj['identity']),
                             'table_kind': classified.get('table_kind', 'uncertain'),
                             'table_classification': classified['table_classification']})
        if any(not isinstance(r, dict) or not any(r.get('identity') == obj['identity'] for obj in adjacent) for r in reviews):
            return finish('continuation_identity_mismatch')
        item['continuation'] = _continuation(response.get('continuation'), identity, content, known)
        if item['table_kind'] != 'calculation_sheet' and item['continuation']['status'] == 'proposed':
            item['continuation'] = {'status': 'conflict', 'reason': 'continuation_evidence_conflict'}
        all_known = [*known, {'identity': identity, 'source_text': content, 'table_kind': item['table_kind']}]
        for review in reviewed:
            original = next(obj for obj in adjacent if obj['identity'] == review['identity'])
            raw_review = next(r for r in reviews if r.get('identity') == review['identity'])
            if review['table_kind'] == 'calculation_sheet':
                review['continuation'] = _continuation(raw_review.get('continuation'), review['identity'],
                                                       original['source_text'], all_known)
        item['continuation']['reviewed_objects'] = reviewed
        return finish()
    except PhysicalRequestBudgetExceeded:
        return finish('table_analysis_physical_budget_exhausted')
    except TimeoutError:
        return finish('calculation_provider_timeout')
    except ValueError as exc:
        # Only our own bounded validation codes may be returned; never provider text.
        reason = str(exc)
        return finish(reason if calls == 0 or reason in RESPONSE_CODES else 'calculation_provider_failed')
    except Exception:
        return finish('calculation_provider_failed')
