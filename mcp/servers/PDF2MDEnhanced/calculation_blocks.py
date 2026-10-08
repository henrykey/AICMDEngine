"""Image-layout calculation crops; never depend on PDF text or vector rules."""
from pathlib import Path
import math


def _valid(box):
    return (isinstance(box, list) and len(box) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in box)
            and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)


def calculation_block_boxes(regions, bbox):
    """Keep every pixel of the object, including headings, conditions and notes."""
    if not _valid(bbox) or not isinstance(regions, list) or not 2 <= len(regions) <= 16:
        return []
    boxes = [region.get('bbox') if isinstance(region, dict) else None for region in regions]
    if any(not _valid(box) or box[0] < bbox[0] or box[1] < bbox[1]
           or box[2] > bbox[2] or box[3] > bbox[3] for box in boxes):
        return []
    boxes.sort(key=lambda box: box[1])
    # Side-by-side or overlapping sections cannot safely become full-width bands.
    if any(a[3] >= b[1] for a, b in zip(boxes, boxes[1:])):
        return []
    cuts = [(a[3] + b[1]) / 2 for a, b in zip(boxes, boxes[1:])]
    boundaries = [bbox[1], *cuts, bbox[3]]
    return [[bbox[0], a, bbox[2], b] for a, b in zip(boundaries, boundaries[1:])]


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


def transcribe_calculation_blocks(image_path, bbox, ocr, directory, dpi=300, layout=None, vlm=None):
    from PIL import Image
    from .page_processor import _crop_layout_block_image
    from .layout_ledger import build_layout_outcome
    manifest = {'mode': 'blocks', 'status': 'fallback', 'reason': 'no_reliable_section_boundaries',
                'blocks': [], 'logical_calls': 0, 'layout_calls': 0, 'vlm_calls': 0}
    if not _valid(bbox):
        manifest['reason'] = 'invalid_object_geometry'
        return None, manifest
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    boxes = calculation_block_boxes(_formula_sections(layout or [], bbox), bbox)
    if not boxes:
        # Parse the actual object image, not a whole-table PDF bounding box.
        try:
            crop, _ = _crop_layout_block_image(Path(image_path), {'bbox': bbox}, directory,
                                               padding_ratio=0, source_dpi=dpi, max_dpi=None)
        except Exception:
            manifest['reason'] = 'object_crop_failed'
            return None, manifest
        regions = []
        if getattr(ocr, 'use_layout_parsing', False) and callable(getattr(ocr, 'parse_layout', None)):
            try:
                manifest['logical_calls'] += 1
                manifest['layout_calls'] += 1
                raw = ocr.parse_layout(str(crop))
                with Image.open(crop) as image:
                    outcome = build_layout_outcome(raw, 1, *image.size)
                regions = _formula_sections(outcome['layout'], [0, 0, 1, 1])
            except Exception:
                regions = []
        if not calculation_block_boxes(regions, [0, 0, 1, 1]) and vlm is not None and vlm.enabled:
            try:
                manifest['vlm_calls'] += 1
                regions = vlm.calculation_sections(str(crop)).get('sections', [])
            except Exception:
                regions = []
        object_boxes = calculation_block_boxes(regions, [0, 0, 1, 1])
        boxes = [[bbox[0], bbox[1] + box[1]*(bbox[3]-bbox[1]),
                  bbox[2], bbox[1] + box[3]*(bbox[3]-bbox[1])] for box in object_boxes]
    if not boxes:
        return None, manifest
    # A missed layout box must not authorize cutting through visible formula ink.
    try:
        with Image.open(image_path) as image:
            gray = image.convert('L')
            left, right = math.floor(bbox[0]*image.width), math.ceil(bbox[2]*image.width)
            for box in boxes[:-1]:
                cut = round(box[3]*image.height)
                strip = gray.crop((left, max(0, cut-1), right, min(image.height, cut+2)))
                for y in range(strip.height):
                    dark = sum(count for shade, count in enumerate(strip.crop((0,y,strip.width,y+1)).histogram()) if shade < 200)
                    if dark > max(2, strip.width*.01):
                        manifest['reason'] = 'block_boundary_intersects_content'
                        return None, manifest
    except Exception:
        manifest['reason'] = 'image_validation_failed'
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
            manifest['logical_calls'] += 1
            result = ocr.extract_page(str(crop))
            text = result.markdown or result.page_text
            if not isinstance(text, str) or not text.strip():
                raise ValueError('empty_block')
            block.update(status='complete', text=text)
            chunks.append(text)
        except Exception:
            block['status'] = 'failed'
            manifest.update(status='fallback', reason='block_transcription_failed')
            return None, manifest
    manifest.update(status='complete', reason=None)
    return '\n\n'.join(chunks), manifest
