from types import SimpleNamespace
import importlib.util
from pathlib import Path

import pytest


def load_pdf_render_utils():
    module_path = Path(__file__).parents[3] / "deepdoc" / "parser" / "pdf_render_utils.py"
    spec = importlib.util.spec_from_file_location("pdf_render_utils", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_get_safe_pdf_zoomin_caps_long_page_pixels():
    pages = [SimpleNamespace(width=612, height=17712)]

    zoomin = load_pdf_render_utils().get_safe_pdf_zoomin(pages, requested_zoomin=3, max_pixels=50_000_000)

    rendered_pixels = pages[0].width * pages[0].height * zoomin * zoomin
    assert zoomin < 3
    assert rendered_pixels <= 50_000_000


def test_get_safe_pdf_zoomin_keeps_normal_page_zoomin():
    pages = [SimpleNamespace(width=612, height=792)]

    assert load_pdf_render_utils().get_safe_pdf_zoomin(pages, requested_zoomin=3, max_pixels=50_000_000) == 3


def test_get_safe_pdf_zoomin_caps_longest_side():
    pages = [SimpleNamespace(width=612, height=17712)]

    zoomin = load_pdf_render_utils().get_safe_pdf_zoomin(
        pages,
        requested_zoomin=3,
        max_pixels=50_000_000,
        max_side=16_000,
    )

    assert pages[0].height * zoomin <= 16_000


def test_get_pdf_page_slices_splits_long_rendered_page():
    page = SimpleNamespace(width=612, height=17712)

    slices = load_pdf_render_utils().get_pdf_page_slices(page, zoomin=3, max_rendered_slice_height=4096)

    assert len(slices) > 1
    assert slices[0] == (0, 0.0, 612.0, 4096 / 3)
    assert slices[-1][3] == 17712.0
    assert all((bottom - top) * 3 <= 4096.1 for _, top, _, bottom in slices)


def test_get_pdf_page_slices_overlaps_neighboring_slices():
    page = SimpleNamespace(width=612, height=17712)

    slices = load_pdf_render_utils().get_pdf_page_slices(
        page,
        zoomin=3,
        max_rendered_slice_height=4096,
        rendered_overlap=256,
    )

    first_bottom = slices[0][3]
    second_top = slices[1][1]
    assert first_bottom - second_top == pytest.approx(256 / 3)
