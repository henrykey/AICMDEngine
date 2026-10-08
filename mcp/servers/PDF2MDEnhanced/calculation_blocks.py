"""Conservative, object-scoped PDF section crops for calculation transcription."""
from pathlib import Path
import math
import fitz


def calculation_block_boxes(page, bbox):
    """Cover the entire object; split only at text-free full-width section rules."""
    if (not isinstance(bbox, list) or len(bbox) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bbox)
            or not 0 <= bbox[0] < bbox[2] <= 1 or not 0 <= bbox[1] < bbox[3] <= 1):
        return []
    if page.rotation:
        return []
    rect = page.rect
    obj = fitz.Rect(bbox[0]*rect.width, bbox[1]*rect.height,
                    bbox[2]*rect.width, bbox[3]*rect.height)
    words = page.get_text('words', clip=obj)
    if not words:  # Scanned pages require a reliable layout path; no guessed slicing.
        return []
    lines = []
    for drawing in page.get_drawings():
        for part in drawing['items']:
            if part[0] != 'l':
                continue
            a, b = part[1:3]
            if (abs(a.y-b.y) < .5 and obj.y0 < a.y < obj.y1
                    and min(a.x,b.x) >= obj.x0-3 and max(a.x,b.x) <= obj.x1+3
                    and abs(a.x-b.x) >= .8*obj.width):
                lines.append(a.y)
    merged = []
    for y in sorted(lines):
        if not merged or y-merged[-1] > 1:
            merged.append(y)
    cuts = []
    for top, bottom in zip(merged, merged[1:]):
        if not 6 < bottom-top < 20:
            continue
        header = [w for w in words if top <= (w[1]+w[3])/2 <= bottom]
        # Heading bands must have real text, not equations or a row of numbers.
        text = ' '.join(w[4] for w in header)
        if len(header) < 2 or any(c in text for c in '=<>≤≥') or sum(c.isalpha() for c in text) < 6:
            continue
        if any(w[1]+.5 < top < w[3]-.5 for w in words):
            continue
        cuts.append(top)
    # Avoid a separate title-only crop. Attach it to the first formula section.
    if cuts:
        cuts = cuts[1:]
    boundaries = [obj.y0, *cuts, obj.y1]
    if not cuts or len(boundaries) > 17:
        return []
    return [[bbox[0], a/rect.height, bbox[2], b/rect.height]
            for a,b in zip(boundaries,boundaries[1:])]


def transcribe_calculation_blocks(page, image_path, bbox, ocr, directory, dpi=300):
    from .page_processor import _crop_layout_block_image
    boxes = calculation_block_boxes(page, bbox)
    manifest = {'mode': 'blocks', 'status': 'fallback', 'reason': 'no_reliable_section_boundaries',
                'blocks': [], 'logical_calls': 0}
    if not boxes:
        return None, manifest
    chunks = []
    for index, box in enumerate(boxes):
        block = {'id': f'b{index+1}', 'bbox': box, 'bbox_space': 'normalized_page', 'status': 'pending'}
        manifest['blocks'].append(block)
        try:
            block_dir = Path(directory)/f'block-{index+1}'
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
