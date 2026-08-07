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


def test_mineru_working_stem_is_utf8_bounded_and_collision_resistant(monkeypatch):
    module = load_mineru_parser(monkeypatch)
    shared_prefix = "超长中文文件名" * 30

    first = module._mineru_working_stem(shared_prefix + "甲")
    second = module._mineru_working_stem(shared_prefix + "乙")

    assert len(first.encode("utf-8")) <= module.MAX_MINERU_WORKING_STEM_BYTES
    assert len(second.encode("utf-8")) <= module.MAX_MINERU_WORKING_STEM_BYTES
    assert first != second
    assert first.rsplit("_", 1)[1].isalnum()
    assert len(first.rsplit("_", 1)[1]) == 12
    assert module._mineru_working_stem("short中文") == "short中文"


def _stub_mineru_parse(parser, monkeypatch, captured):
    monkeypatch.setattr(parser, "__images__", lambda *args, **kwargs: None)

    def fake_run(input_path, output_dir, options, callback=None):
        captured["input_path"] = input_path
        captured["working_stem"] = input_path.stem
        assert input_path.is_file()
        return output_dir

    def fake_read(output_dir, file_stem, method="auto", backend="pipeline"):
        captured["read_stem"] = file_stem
        return []

    monkeypatch.setattr(parser, "_run_mineru", fake_run)
    monkeypatch.setattr(parser, "_read_output", fake_read)


def test_parse_pdf_uses_bounded_working_name_for_binary(monkeypatch):
    module = load_mineru_parser(monkeypatch)
    parser = module.MinerUParser()
    captured = {}
    _stub_mineru_parse(parser, monkeypatch, captured)

    parser.parse_pdf(f"{'超长名称' * 30}.pdf", b"%PDF-1.7")

    assert len(captured["working_stem"].encode("utf-8")) <= module.MAX_MINERU_WORKING_STEM_BYTES
    assert captured["read_stem"] == captured["working_stem"]


def test_parse_pdf_copies_renamed_local_input_without_modifying_source(tmp_path, monkeypatch):
    module = load_mineru_parser(monkeypatch)
    parser = module.MinerUParser()
    captured = {}
    _stub_mineru_parse(parser, monkeypatch, captured)
    source = tmp_path / f"{'本地超长名称' * 20}.pdf"
    source.write_bytes(b"%PDF-1.7")

    parser.parse_pdf(str(source), None)

    assert source.read_bytes() == b"%PDF-1.7"
    assert captured["input_path"] != source
    assert not captured["input_path"].exists()
    assert captured["read_stem"] == captured["working_stem"]
