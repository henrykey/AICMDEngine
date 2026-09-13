"""Bounded, identity-scoped processing behind the existing table extraction tool."""
from copy import deepcopy
import re

from .calculation_sheet import (
    apply_calculation_sheet, calculation_budget, parse_calculation_sheet, source_context,
    PhysicalRequestBudgetExceeded,
)


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


def _read_response(item, response, identity, hint, mode, language):
    if (not isinstance(response, dict) or response.get('object_ref') != identity['layout_id']
            or response.get('source_sha256') != identity['source_sha256']):
        raise ValueError('calculation_identity_mismatch')
    content = item.get('existing_content', '') if mode == 'organize_existing' else response.get('source_text')
    if not isinstance(content, str) or not content.strip() or len(content) > 100000:
        raise ValueError('calculation_source_missing')
    if mode == 'organize_existing' and response.get('source_text', content) != content:
        raise ValueError('calculation_source_rewritten')
    if mode == 'organize_existing':
        response = deepcopy(response)
        for section in response.get('sections', []) if isinstance(response.get('sections'), list) else []:
            if not isinstance(section, dict) or not isinstance(section.get('items'), list):
                continue
            for entry in section['items']:
                if isinstance(entry, dict):
                    entry.pop('bbox', None)
    ctx = source_context(content); ctx['description_language'] = language
    if hint == 'auto':
        apply_calculation_sheet(item, {**response, 'calculation_sheet': response}, content, language)
    else:
        item['table_classification'] = {'kind': hint, 'status': 'manual_confirmed',
                                        'reason': 'manual_type_constraint', 'evidence': []}
        if hint == 'calculation_sheet':
            item['calculation_sheet'] = parse_calculation_sheet(response, ctx, item)
    # Keep image transcription separate from the full-document identity hash.
    item['calculation_source'] = ctx
    if mode != 'organize_existing':
        item['calculation_source']['origin'] = 'image_transcription'
    else:
        item['calculation_source']['origin'] = 'existing_content'
        for section in item.get('calculation_sheet', {}).get('sections', []):
            for entry in section['items']:
                entry['source']['location_scope'] = 'source_text'
    if item['table_kind'] == 'calculation_sheet':
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


def process_request(request, hint, mode, vlm, image_path=None, adjacent_images=None):
    """One primary call and at most one joint review, sharing the configured budget."""
    item = initial_item(request, hint, mode)
    calls = 0
    def finish(reason=None):
        result = result_for(item, calls, reason)
        if getattr(vlm, 'physical_request_limit', None) is not None:
            result['budget'].update(physical_requests=vlm.physical_requests,
                                     physical_request_limit=vlm.physical_request_limit, sdk_retries=0)
        return result
    try:
        validate_request(request, hint, mode)
        identity = request['identity']
        if getattr(vlm, 'physical_request_limit', None) == 0:
            return finish('table_analysis_physical_budget_exhausted')
        if calculation_budget(vlm) == 0:
            return finish('table_analysis_budget_exhausted')
        target = {'object_ref': identity['layout_id'], 'source_sha256': identity['source_sha256'],
                  'processing_mode': mode, 'table_kind_hint': hint,
                  'existing_content': request.get('existing_content', '')}
        if mode != 'organize_existing' and not image_path:
            return finish('source_image_unavailable')
        calls += 1
        response = vlm.extract_calculation_sheet(image_path, target)
        if getattr(vlm, 'last_call_info', {}).get('finish_reason') in {'length', 'content_filter', 'tool_calls'}:
            return finish('calculation_response_incomplete')
        content = _read_response(item, response, identity, hint, mode, getattr(vlm, 'description_language', 'unknown'))
        if mode == 'organize_existing':
            item['continuation'] = {'status': 'none', 'reason': 'not_assessed_text_only'}
            return finish()
        raw_continuation = response.get('continuation')
        needs_context = (item['table_kind'] == 'uncertain' or response.get('continuation_required') is True
                         or isinstance(raw_continuation, dict) and raw_continuation.get('status') in ('pending', 'proposed'))
        adjacent = request.get('adjacent_objects', [])
        if not needs_context:
            item['continuation'] = _continuation(raw_continuation, identity, content, [])
            return finish()
        item['continuation'] = {'status': 'pending', 'reason': 'adjacent_context_required'}
        if not adjacent:
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
        if getattr(vlm, 'last_call_info', {}).get('finish_reason') in {'length', 'content_filter', 'tool_calls'}:
            return finish('calculation_response_incomplete')
        content = _read_response(item, response, identity, hint, mode, getattr(vlm, 'description_language', 'unknown'))
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
        return finish(reason if calls == 0 or reason in {
            'calculation_identity_mismatch', 'calculation_source_missing', 'calculation_source_rewritten'
        } else 'calculation_provider_failed')
    except Exception:
        return finish('calculation_provider_failed')
