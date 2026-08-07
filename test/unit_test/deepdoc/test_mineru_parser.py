import importlib.util
import json
import sys
import types
from enum import StrEnum
from pathlib import Path


def load_mineru_parser(monkeypatch):
    stub_modules = {
        "deepdoc": {},
        "deepdoc.parser": {},
        "deepdoc.parser.pdf_parser": {"RAGFlowPdfParser": object},
        "numpy": {},
        "pdfplumber": {},
        "requests": {},
        "PIL": {},
        "PIL.Image": {},
        "strenum": {"StrEnum": StrEnum},
    }

    for name, attrs in stub_modules.items():
        module = types.ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(module, attr_name, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_path = Path(__file__).parents[3] / "deepdoc" / "parser" / "mineru_parser.py"
    spec = importlib.util.spec_from_file_location("mineru_parser_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_output_finds_content_list_under_auto_directory(tmp_path, monkeypatch):
    output_dir = tmp_path / "456_auto_rzs25vv3"
    auto_dir = output_dir / "auto"
    auto_dir.mkdir(parents=True)
    content_list = [
        {
            "type": "text",
            "text": "hello",
            "page_idx": 0,
            "bbox": [0, 0, 100, 100],
        }
    ]
    (auto_dir / "456_content_list.json").write_text(json.dumps(content_list), encoding="utf-8")

    outputs = load_mineru_parser(monkeypatch).MinerUParser()._read_output(output_dir, "456", method="auto")

    assert outputs == content_list


def test_read_output_falls_back_to_recursive_content_list_search(tmp_path, monkeypatch):
    output_dir = tmp_path / "456(1)_auto_1p2_jlbk"
    auto_dir = output_dir / "auto"
    auto_dir.mkdir(parents=True)
    content_list = [
        {
            "type": "text",
            "text": "from recursive search",
            "page_idx": 0,
            "bbox": [0, 0, 100, 100],
        }
    ]
    (auto_dir / "456_content_list.json").write_text(json.dumps(content_list), encoding="utf-8")

    outputs = load_mineru_parser(monkeypatch).MinerUParser()._read_output(output_dir, "456(1)", method="auto")

    assert outputs == content_list


def test_read_output_finds_content_list_under_mineru_nested_auto_directory(tmp_path, monkeypatch):
    file_stem = "GBT14837.1-2014橡胶和橡胶制品热重分析法"
    output_dir = tmp_path / "mineru-output"
    auto_dir = output_dir / file_stem / "auto"
    auto_dir.mkdir(parents=True)
    content_list = [
        {
            "type": "text",
            "text": "from MinerU nested auto directory",
            "page_idx": 0,
            "bbox": [0, 0, 100, 100],
        }
    ]
    (auto_dir / f"{file_stem}_content_list.json").write_text(json.dumps(content_list), encoding="utf-8")

    def fail_recursive_search(*args, **kwargs):
        raise AssertionError("the known MinerU directory layout should not need recursive search")

    monkeypatch.setattr(Path, "rglob", fail_recursive_search)

    outputs = load_mineru_parser(monkeypatch).MinerUParser()._read_output(output_dir, file_stem, method="auto")

    assert outputs == content_list
