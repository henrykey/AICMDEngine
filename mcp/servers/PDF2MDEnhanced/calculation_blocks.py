"""Image-layout calculation crops; never depend on PDF text or vector rules."""
from pathlib import Path
import math


def _valid(box):
    return (isinstance(box, list) and len(box) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in box)
            and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)


def normalize_calculation_regions(response, image_size):
    """Use declared units; never guess a coordinate scale from its magnitude."""
    space = response.get('coordinate_space', 'normalized')
    scales = {'normalized': (1, 1), 'normalized_1000': (1000, 1000), 'pixels': image_size}
    if space not in scales:
        raise ValueError('unknown_coordinate_space')
    sx, sy = scales[space]
    def convert(box):
        if not isinstance(box, list) or len(box) != 4 or any(type(x) not in (int, float) for x in box):
            raise ValueError('invalid_section_geometry')
        result = [box[0]/sx, box[1]/sy, box[2]/sx, box[3]/sy]
        if not _valid(result):
            raise ValueError('invalid_section_geometry')
        return result
    return convert(response['object_bbox']), [{'bbox': convert(r['bbox'])} for r in response['sections']]


def calculation_block_boxes(regions, bbox):
    """Partition the complete object into reading-order rectangles, retaining columns."""
    if not _valid(bbox) or not isinstance(regions, list) or not 2 <= len(regions) <= 16:
        return []
    boxes = [r.get('bbox') if isinstance(r, dict) else None for r in regions]
    if any(not _valid(b) or b[0] < bbox[0] or b[1] < bbox[1]
           or b[2] > bbox[2] or b[3] > bbox[3] for b in boxes):
        return []
    def partition(items, area):
        if len(items) == 1:
            return [area]
        # Prefer top-to-bottom groups; split columns only inside a shared row band.
        for axis in (1, 0):
            ordered = sorted(items, key=lambda b: b[axis])
            end = ordered[0][axis+2]
            for i in range(1, len(ordered)):
                if end <= ordered[i][axis]:
                    cut = (end + ordered[i][axis])/2
                    first, second = list(area), list(area)
                    first[axis+2], second[axis] = cut, cut
                    left, right = partition(ordered[:i], first), partition(ordered[i:], second)
                    return left + right if left and right else []
                end = max(end, ordered[i][axis+2])
        return []
    return partition(boxes, list(bbox))


def boundary_intersects_content(image, bbox):
    """Detect ink crossing crop edges; thin separator rules alone are not glyphs."""
    from PIL import ImageChops
    gray = image.convert('L')
    x0, y0, x1, y1 = [round(v*s) for v,s in zip(bbox, (image.width,image.height,image.width,image.height))]
    def crossing(axis, cut, start, end):
        limit = image.height if axis == 1 else image.width
        if cut <= 3 or cut >= limit-3:
            return False
        if axis == 1:
            a, b = (start,cut-3,end,cut-2), (start,cut+2,end,cut+3)
        else:
            a, b = (cut-3,start,cut-2,end), (cut+2,start,cut+3,end)
        first = gray.crop(a).point(lambda p: 255 if p < 200 else 0)
        second = gray.crop(b).point(lambda p: 255 if p < 200 else 0)
        dark = ImageChops.multiply(first, second).histogram()[255]
        return dark > max(2, (end-start)*.01)
    return (crossing(1,y0,x0,x1) or crossing(1,y1,x0,x1)
            or crossing(0,x0,y0,y1) or crossing(0,x1,y0,y1))


def _formula_sections(layout, bbox):
    """Attach following conditions/notes to each formula; reject crossing content."""
    if any(not isinstance(item, dict) or not _valid(item.get('bbox')) for item in layout):
        return []
    entries = [item for item in layout if _valid(item.get('bbox'))
               and item['bbox'][0] >= bbox[0] and item['bbox'][1] >= bbox[1]
               and item['bbox'][2] <= bbox[2] and item['bbox'][3] <= bbox[3]
               and item.get('type') != 'table']
    formulas = sorted([item for item in entries if item.get('type') == 'formula'],
                      key=lambda item: item['bbox'][1])
    if len(formulas) < 2:
        return []
    sections = []
    for index, formula in enumerate(formulas):
        box = list(formula['bbox'])
        end = formulas[index+1]['bbox'][1] if index+1 < len(formulas) else bbox[3]
        for item in entries:
            if box[1] <= item['bbox'][1] < end:
                box[0] = min(box[0], item['bbox'][0])
                box[2] = max(box[2], item['bbox'][2])
                box[3] = max(box[3], item['bbox'][3])
        sections.append({'bbox': box})
    return sections


class BudgetedCalculationOcr:
    """Share the existing calculation budget across OCR and VLM calls."""
    def __init__(self, ocr, vlm):
        self.ocr = ocr
        self.vlm = vlm
        self.use_layout_parsing = ocr.use_layout_parsing

    def _call(self, method, path):
        self.vlm.reserve_automatic_calculation_calls(1)
        previous_guard = getattr(self.ocr, 'request_guard', None)
        self.ocr.request_guard = self.vlm._count_physical_request
        try:
            return method(path)
        finally:
            self.ocr.request_guard = previous_guard

    def extract_page(self, path):
        return self._call(self.ocr.extract_page, path)

    def parse_layout(self, path):
        return self._call(self.ocr.parse_layout, path)


def transcribe_calculation_blocks(image_path, bbox, ocr, directory, dpi=300, *, blocks=None, engine=None,
                                 vlm=None, review_evidence=None):
    """Transcribe exactly the caller-selected rectangles with its selected engine."""
    from PIL import Image
    from .page_processor import _crop_layout_block_image
    manifest = {'mode': 'blocks', 'status': 'failed', 'reason': 'explicit_blocks_required',
                'blocks': [], 'logical_calls': 0, 'layout_calls': 0, 'vlm_calls': 0}
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 16:
        return None, manifest
    if engine not in ('ocr', 'vlm'):
        manifest['reason'] = 'explicit_engine_required'
        return None, manifest
    if not _valid(bbox) or any(not _valid(b) or b[0] < bbox[0] or b[1] < bbox[1]
            or b[2] > bbox[2] or b[3] > bbox[3] for b in blocks):
        manifest['reason'] = 'invalid_section_geometry'
        return None, manifest
    if any(max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])
           for index, a in enumerate(blocks) for b in blocks[index + 1:]):
        manifest['reason'] = 'overlapping_sections'
        return None, manifest
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(image_path) as source:
            image = source.convert('L')
    except Exception:
        manifest['reason'] = 'object_crop_failed'
        return None, manifest
    manifest['original_bbox'] = list(bbox)
    effective = list(bbox)
    boxes = [list(box) for box in blocks]
    if any(boundary_intersects_content(image, box) for box in boxes):
        manifest['reason'] = 'block_boundary_intersects_content'
        return None, manifest
    manifest['layout_source'] = 'caller'
    manifest['effective_bbox'] = effective
    use_vlm = engine == 'vlm'
    if use_vlm and (vlm is None or not vlm.enabled):
        manifest['reason'] = 'calculation_vlm_unavailable'
        return None, manifest
    manifest['engine'] = 'vlm_blocks' if use_vlm else 'glm_ocr_blocks'
    context_crop = None
    if use_vlm and manifest['mode'] == 'blocks':
        try:
            context_crop, _ = _crop_layout_block_image(Path(image_path), {'bbox': effective}, directory,
                                                       padding_ratio=0, source_dpi=dpi, max_dpi=None)
        except Exception:
            manifest['reason'] = 'object_crop_failed'
            return None, manifest
    chunks = []
    for index, box in enumerate(boxes):
        block = {'id': f'b{index+1}', 'bbox': box, 'bbox_space': 'normalized_page', 'status': 'pending'}
        manifest['blocks'].append(block)
        try:
            block_dir = directory / f'block-{index+1}'
            block_dir.mkdir(parents=True, exist_ok=True)
            crop, _ = _crop_layout_block_image(Path(image_path), {'bbox': box}, block_dir,
                                               padding_ratio=0, source_dpi=dpi, max_dpi=None)
            if use_vlm:
                vlm.reserve_automatic_calculation_calls(1)
                manifest['vlm_calls'] += 1
                text = vlm.transcribe_calculation_block(str(crop), logical_reorder=True,
                    **({'context_image': str(context_crop)} if context_crop else {}),
                    **({'review_evidence': review_evidence} if review_evidence else {}))
            else:
                manifest['logical_calls'] += 1
                result = ocr.extract_page(str(crop))
                text = result.markdown or result.page_text
            if not isinstance(text, str) or not text.strip():
                raise ValueError('empty_block')
            block.update(status='complete', text=text)
            chunks.append(text)
        except Exception as exc:
            block.update(status='failed', error_type=type(exc).__name__)
            manifest.update(status='failed', reason='block_transcription_failed')
            return None, manifest
    manifest.update(status='complete', reason=None)
    return '\n\n'.join(chunks), manifest
