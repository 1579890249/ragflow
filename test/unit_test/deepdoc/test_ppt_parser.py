import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from PIL import Image


def load_ppt_parser(monkeypatch):
    pptx_module = types.ModuleType("pptx")
    pptx_module.Presentation = lambda *_args, **_kwargs: SimpleNamespace(slides=[])
    monkeypatch.setitem(sys.modules, "pptx", pptx_module)

    module_path = Path(__file__).parents[3] / "deepdoc" / "parser" / "ppt_parser.py"
    spec = importlib.util.spec_from_file_location("ppt_parser_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_ppt_bytes_are_converted_before_text_extraction(tmp_path, monkeypatch):
    module = load_ppt_parser(monkeypatch)
    converted = tmp_path / "legacy.pptx"
    converted.write_bytes(b"PK\x03\x04")
    presentation_args = []

    def fake_convert(_self, input_path, output_dir):
        assert Path(input_path).suffix == ".ppt"
        assert Path(output_dir).exists()
        return converted

    def fake_presentation(arg):
        presentation_args.append(arg)
        assert isinstance(arg, (str, Path))
        assert Path(arg).suffix == ".pptx"
        return SimpleNamespace(slides=[SimpleNamespace(shapes=[])])

    monkeypatch.setattr(module.RAGFlowPptParser, "_convert_to_pptx", fake_convert, raising=False)
    monkeypatch.setattr(module, "Presentation", fake_presentation)

    assert module.RAGFlowPptParser()(b"\xd0\xcf\x11\xe0legacy-ppt", 0, 10) == [""]
    assert presentation_args == [converted]


def test_ppt_to_pil_images_uses_ppt_suffix_for_legacy_bytes(tmp_path, monkeypatch):
    module = load_ppt_parser(monkeypatch)
    converter_inputs = []

    class FakeConverter:
        def __init__(self, pptx_path, output_dir, temp_dir):
            converter_inputs.append(Path(pptx_path))
            self.output_dir = Path(output_dir)

        def convert(self):
            self.output_dir.mkdir(parents=True, exist_ok=True)
            image_path = self.output_dir / "slide_1.jpeg"
            Image.new("RGB", (8, 8), "white").save(image_path)
            return [str(image_path)]

    monkeypatch.setattr(module, "PPTXToImageConverter", FakeConverter)

    images = module.RAGFlowPptParser().ppt_to_pil_images(
        b"\xd0\xcf\x11\xe0legacy-ppt",
        temp_ori_dir=str(tmp_path),
    )

    assert converter_inputs[0].suffix == ".ppt"
    assert len(images) == 1


def test_dps_bytes_are_converted_before_text_extraction(tmp_path, monkeypatch):
    module = load_ppt_parser(monkeypatch)
    converted = tmp_path / "slides.pptx"
    converted.write_bytes(b"PK\x03\x04")
    converted_inputs = []

    def fake_convert(_self, input_path, output_dir):
        converted_inputs.append(Path(input_path))
        assert Path(output_dir).exists()
        return converted

    def fake_presentation(arg):
        assert Path(arg).suffix == ".pptx"
        return SimpleNamespace(slides=[SimpleNamespace(shapes=[])])

    monkeypatch.setattr(module.RAGFlowPptParser, "_convert_to_pptx", fake_convert, raising=False)
    monkeypatch.setattr(module, "Presentation", fake_presentation)

    assert module.RAGFlowPptParser()(b"dps-bytes", 0, 10, input_suffix=".dps") == [""]
    assert converted_inputs[0].suffix == ".dps"
