
from .model_errors import raise_model_error
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


def _boundary_crossings(image, bbox, allow_thin_rules):
    """Detect crossing ink; only calculation partitions may ignore thin rules.

    A figure dimension extension is content even when only one stroke crosses
    a wide crop. Cell-image crops must not use the partition separator allowance.
    """
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
        return dark > (max(2, (end-start)*.01) if allow_thin_rules else 0)
    return (crossing(0,x0,y0,y1), crossing(1,y0,x0,x1),
            crossing(0,x1,y0,y1), crossing(1,y1,x0,x1))

def boundary_intersects_content(image, bbox, *, allow_thin_rules=True):
    return any(_boundary_crossings(image, bbox, allow_thin_rules))


def image_has_foreground(image, bbox, table_bbox):
    """Ignore only full-table horizontal rules when checking a candidate crop.

    Pale background or a rule alone is insufficient evidence of an illustration;
    callers must retry localization, not discard the source table.
    """
    scales = image.size * 2
    box = [round(v * scale) for v, scale in zip(bbox, scales)]
    table = [round(v * scale) for v, scale in zip(table_bbox, scales)]
    ink = image.convert('L').point(lambda p: 255 if p < 200 else 0)
    for y in range(box[1], box[3]):
        if ink.crop((box[0], y, box[2], y + 1)).getbbox() is None:
            continue
        if ink.crop((table[0], y, table[2], y + 1)).histogram()[255] < .95 * (table[2] - table[0]):
            return True
    return False


def _trim_crossed_table_rules(image, box, limits, margin, grid_shape=None):
    """Remove only table-spanning rules and blank space at a crop edge."""
    from PIL import ImageDraw
    if (not isinstance(grid_shape, tuple) or len(grid_shape) != 2
            or any(type(n) is not int or n < 1 for n in grid_shape)):
        return box
    ink = image.convert('L').point(lambda p: 255 if p < 200 else 0)
    mask = ink.copy()
    draw = ImageDraw.Draw(mask)
    rules = [[], []]
    for axis in (0, 1):
        start = max(0, limits[axis] - margin * 2)
        end = min(image.size[axis], limits[axis + 2] + margin * 2)
        length = limits[3 - axis] - limits[1 - axis]
        for position in range(start, end):
            strip = ((position, limits[1], position + 1, limits[3]) if axis == 0
                     else (limits[0], position, limits[2], position + 1))
            if ink.crop(strip).histogram()[255] >= .75 * length:
                if rules[axis] and position == rules[axis][-1][-1] + 1:
                    rules[axis][-1].append(position)
                else:
                    rules[axis].append([position])
    # A single long dimension line is not enough to establish a table rule.
    if any(len(groups) < 2 for groups in rules):
        return box
    for axis in (0, 1):
        rules[axis] = [group for group in rules[axis] if len(group) <= margin * 2]
        for group in rules[axis]:
            a, b = group[0] - 2, group[-1] + 2
            draw.rectangle((a, limits[1], b, limits[3]) if axis == 0
                           else (limits[0], a, limits[2], b), fill=0)
    if any(len(groups) < 2 for groups in rules):
        return box
    # Require the complete expected grid and evidence for both outer edges;
    # otherwise a drawing stroke could replace an unseen separator.
    for axis, expected in ((0, grid_shape[1] + 1), (1, grid_shape[0] + 1)):
        groups = rules[axis]
        tolerance = max(margin * 2, round((limits[axis + 2] - limits[axis]) * (.01 if axis == 0 else .06)))
        if (len(groups) != expected or abs(groups[0][0] - limits[axis]) > tolerance
                or abs(limits[axis + 2] - groups[-1][-1]) > tolerance):
            return box
    trimmed = list(box)
    for edge in range(4):
        axis = edge % 2
        extent = box[axis + 2] - box[axis]
        for group in rules[axis]:
            a, b = group[0], group[-1]
            if edge < 2 and box[edge] <= a and b - box[edge] <= extent * .1:
                cut = b + margin + 1
                strip = list(trimmed); strip[axis + 2] = cut
            elif edge >= 2 and box[edge] >= b and box[edge] - a <= extent * .1:
                cut = a - margin
                strip = list(trimmed); strip[axis] = cut
            else:
                continue
            if cut <= trimmed[axis] or cut >= trimmed[axis + 2]:
                continue
            if mask.crop(tuple(strip)).getbbox() is None:
                trimmed[edge] = cut
                break
    return trimmed


def expand_clipped_image_bbox(image, bbox, table_bbox, *, grid_shape=None):
    """Move cut edges to nearby blank bands, bounded by the source table.

    Trim only an adjacent full-table separator; otherwise only expand. Never
    cross the table or search beyond a quarter of the original extent per edge.
    Uncertain/large corrections remain in bounded recovery.
    """
    if not _valid(bbox) or not _valid(table_bbox):
        return None
    scales = (image.width, image.height) * 2
    original = [round(v*s) for v,s in zip(bbox, scales)]
    limits = [round(v*s) for v,s in zip(table_bbox, scales)]
    box = list(original)
    ink = image.convert('L').point(lambda p: 255 if p < 200 else 0)
    margin = max(4, round(min(image.size) / 400))
    box = _trim_crossed_table_rules(image, box, limits, margin, grid_shape)
    # A crop may include the adjacent full-width table separator. It cannot
    # reach a blank vertical edge until that separator alone is trimmed away.
    # Only recognize rules spanning the entire table, never short dimensions.
    for edge in (1, 3):
        direction = 1 if edge == 1 else -1
        rows = range(box[edge], box[edge] + direction * margin * 3, direction)
        rule_rows = []
        for y in rows:
            if not limits[1] <= y < limits[3]:
                break
            whole = ink.crop((limits[0], y, limits[2], y + 1))
            if whole.histogram()[255] >= .95 * (limits[2] - limits[0]):
                rule_rows.append(y)
            elif ink.crop((box[0], y, box[2], y + 1)).histogram()[255] > 3:
                break
        if rule_rows:
            cut = (max(rule_rows) + margin + 1 if edge == 1 else min(rule_rows) - margin)
            strip = (box[0], max(rule_rows) + 1, box[2], cut) if edge == 1 else (box[0], cut, box[2], min(rule_rows))
            if ink.crop(strip).getbbox() is None:
                box[edge] = cut
    # Recheck after expansion: widening one side may expose a cut on another.
    for _ in range(4):
        crossings = _boundary_crossings(image, [v/s for v,s in zip(box, scales)], False)
        if not any(crossings):
            return [v/s for v,s in zip(box, scales)]
        for edge, crossing in enumerate(crossings):
            if not crossing:
                continue
            axis = edge % 2
            direction = -1 if edge < 2 else 1
            budget = (original[axis+2] - original[axis]) // 4
            start = box[edge]
            stop = max(limits[edge], original[edge]-budget) if direction < 0 else min(limits[edge], original[edge]+budget)
            for cut in range(start+direction, stop, direction):
                strip = ([cut-margin, box[1], cut+margin+1, box[3]] if axis == 0
                         else [box[0], cut-margin, box[2], cut+margin+1])
                if strip[axis] < limits[axis] or strip[axis+2] > limits[axis+2]:
                    continue
                if ink.crop(strip).getbbox() is None:
                    box[edge] = cut
                    break
            else:
                return None
    return None



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
    except Exception as exc:
        raise_model_error(exc)
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
        except Exception as exc:
            raise_model_error(exc)
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
            raise_model_error(exc)
            block.update(status='failed', error_type=type(exc).__name__)
            manifest.update(status='failed', reason='block_transcription_failed')
            return None, manifest
    manifest.update(status='complete', reason=None)
    return '\n\n'.join(chunks), manifest
