import math
import os


DEFAULT_MAX_PDF_RENDER_PIXELS = 50_000_000
DEFAULT_MAX_PDF_RENDER_SIDE = 32_768
DEFAULT_MAX_PDF_RENDER_SLICE_HEIGHT = 4096
DEFAULT_MAX_PDF_RENDER_SLICE_OVERLAP = 256


def get_max_pdf_render_pixels():
    raw = os.getenv("MAX_PDF_RENDER_PIXELS")
    if not raw:
        return DEFAULT_MAX_PDF_RENDER_PIXELS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MAX_PDF_RENDER_PIXELS


def get_max_pdf_render_side():
    raw = os.getenv("MAX_PDF_RENDER_SIDE")
    if not raw:
        return DEFAULT_MAX_PDF_RENDER_SIDE
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MAX_PDF_RENDER_SIDE


def get_max_pdf_render_slice_height():
    raw = os.getenv("MAX_PDF_RENDER_SLICE_HEIGHT")
    if not raw:
        return DEFAULT_MAX_PDF_RENDER_SLICE_HEIGHT
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MAX_PDF_RENDER_SLICE_HEIGHT


def get_max_pdf_render_slice_overlap():
    raw = os.getenv("MAX_PDF_RENDER_SLICE_OVERLAP")
    if not raw:
        return DEFAULT_MAX_PDF_RENDER_SLICE_OVERLAP
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MAX_PDF_RENDER_SLICE_OVERLAP


def get_safe_pdf_zoomin(pages, requested_zoomin=3, max_pixels=None, max_side=None):
    if requested_zoomin <= 0:
        return requested_zoomin

    max_pixels = get_max_pdf_render_pixels() if max_pixels is None else max_pixels
    max_side = get_max_pdf_render_side() if max_side is None else max_side

    page_sizes = [(float(page.width), float(page.height)) for page in pages]
    if not page_sizes:
        return requested_zoomin

    safe_zoomin = requested_zoomin
    if max_pixels > 0:
        max_page_area = max((width * height for width, height in page_sizes), default=0)
        if max_page_area > 0:
            requested_pixels = max_page_area * safe_zoomin * safe_zoomin
            if requested_pixels > max_pixels:
                safe_zoomin = math.sqrt(max_pixels / max_page_area)

    if max_side > 0:
        longest_side = max((max(width, height) for width, height in page_sizes), default=0)
        if longest_side > 0:
            safe_zoomin = min(safe_zoomin, max_side / longest_side)

    return safe_zoomin


def get_pdf_page_slices(page, zoomin, max_rendered_slice_height=None, rendered_overlap=None):
    max_rendered_slice_height = get_max_pdf_render_slice_height() if max_rendered_slice_height is None else max_rendered_slice_height
    rendered_overlap = get_max_pdf_render_slice_overlap() if rendered_overlap is None else rendered_overlap
    page_width = float(page.width)
    page_height = float(page.height)

    if zoomin <= 0 or max_rendered_slice_height <= 0 or page_height * zoomin <= max_rendered_slice_height:
        return [(0, 0.0, page_width, page_height)]

    slice_height = max_rendered_slice_height / zoomin
    overlap_height = max(0, min(rendered_overlap, max_rendered_slice_height - 1)) / zoomin
    slices = []
    top = 0.0
    while top < page_height:
        bottom = min(page_height, top + slice_height)
        slices.append((0, top, page_width, bottom))
        if bottom >= page_height:
            break
        next_top = bottom - overlap_height
        top = next_top if next_top > top else bottom
    return slices
