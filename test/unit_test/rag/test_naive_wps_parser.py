import importlib.util
import sys
import types
from pathlib import Path


def load_naive(monkeypatch):
    class FakeDocxParser:
        pass

    stub_modules = {
        "api": {},
        "api.db": {},
        "api.db.services": {},
        "api.db.services.llm_service": {"LLMBundle": object},
        "common": {},
        "common.constants": {
            "LLMType": type(
                "LLMType",
                (),
                {
                    "OCR": type("Value", (), {"value": "ocr"}),
                    "IMAGE2TEXT": "image2text",
                },
            )
        },
        "common.parser_config_utils": {"normalize_layout_recognizer": lambda value: (value, None)},
        "common.token_utils": {"num_tokens_from_string": lambda text: len(text.split())},
        "deepdoc": {},
        "deepdoc.parser": {
            "DocxParser": FakeDocxParser,
            "ExcelParser": object,
            "HtmlParser": object,
            "JsonParser": object,
            "MarkdownElementExtractor": object,
            "MarkdownParser": object,
            "PdfParser": object,
            "TxtParser": object,
        },
        "deepdoc.parser.docling_parser": {"DoclingParser": object},
        "deepdoc.parser.figure_parser": {
            "VisionFigureParser": object,
            "vision_figure_parser_docx_wrapper": lambda sections, tbls, callback=None, **kwargs: tbls,
            "vision_figure_parser_pdf_wrapper": lambda tbls, callback=None, **kwargs: tbls,
        },
        "deepdoc.parser.pdf_parser": {"PlainParser": object, "VisionParser": object},
        "deepdoc.parser.tcadp_parser": {"TCADPParser": object},
        "docx": {"Document": lambda *_args, **_kwargs: object()},
        "docx.image.exceptions": {
            "InvalidImageStreamError": Exception,
            "UnexpectedEndOfFileError": Exception,
            "UnrecognizedImageError": Exception,
        },
        "docx.opc.oxml": {"parse_xml": lambda *_args, **_kwargs: None},
        "docx.opc.pkgreader": {
            "_SerializedRelationship": object,
            "_SerializedRelationships": type("_SerializedRelationships", (), {"load_from_xml": None}),
        },
        "markdown": {"markdown": lambda text, *args, **kwargs: text},
        "PIL": {},
        "PIL.Image": {},
        "rag": {},
        "rag.nlp": {
            "append_context2table_image4pdf": lambda sections, tables, image_context_size: tables,
            "attach_media_context": lambda *args, **kwargs: None,
            "concat_img": lambda left, right: left or right,
            "find_codec": lambda *_args, **_kwargs: "utf-8",
            "naive_merge": lambda sections, *_args, **_kwargs: [section[0] for section in sections],
            "naive_merge_docx": lambda sections, *_args, **_kwargs: ([section[0] for section in sections], [None for _ in sections]),
            "naive_merge_with_images": lambda sections, images, *_args, **_kwargs: ([section[0] for section in sections], images),
            "rag_tokenizer": type(
                "Tokenizer",
                (),
                {
                    "tokenize": staticmethod(lambda text: text),
                    "fine_grained_tokenize": staticmethod(lambda text: text),
                },
            ),
            "tokenize_chunks": lambda chunks, *_args, **_kwargs: [{"content_with_weight": chunk} for chunk in chunks],
            "tokenize_chunks_with_images": lambda chunks, *_args, **_kwargs: [{"content_with_weight": chunk} for chunk in chunks],
            "tokenize_table": lambda *_args, **_kwargs: [],
        },
        "rag.utils": {},
        "rag.utils.file_utils": {
            "extract_embed_file": lambda *_args, **_kwargs: [],
            "extract_html": lambda *_args, **_kwargs: (None, None),
            "extract_links_from_docx": lambda *_args, **_kwargs: [],
            "extract_links_from_pdf": lambda *_args, **_kwargs: [],
        },
    }
    for name, attrs in stub_modules.items():
        module = types.ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(module, attr_name, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_path = Path(__file__).parents[3] / "rag" / "app" / "naive.py"
    spec = importlib.util.spec_from_file_location("naive_under_test_wps", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_general_parser_converts_wps_to_docx_before_parsing(monkeypatch):
    naive = load_naive(monkeypatch)
    converted = []

    def fake_convert(binary, suffix):
        converted.append((binary, suffix))
        return b"docx-bytes"

    class FakeDocx:
        def __call__(self, filename, binary=None):
            assert filename.endswith(".docx")
            assert binary == b"docx-bytes"
            return [("WPS text", None)], []

    monkeypatch.setattr(naive, "convert_office_to_docx", fake_convert, raising=False)
    monkeypatch.setattr(naive, "Docx", FakeDocx)

    chunks = naive.chunk("demo.wps", binary=b"wps-bytes", callback=lambda *_args, **_kwargs: None)

    assert converted == [(b"wps-bytes", ".wps")]
    assert chunks == [{"content_with_weight": "WPS text"}]


def test_general_parser_falls_back_to_pdf_when_wps_docx_conversion_fails(monkeypatch):
    naive = load_naive(monkeypatch)

    def fake_docx_convert(_binary, _suffix):
        raise FileNotFoundError("DOCX file not found after conversion")

    def fake_pdf_convert(binary, suffix):
        assert binary == b"wps-bytes"
        assert suffix == ".wps"
        return b"pdf-bytes"

    def fake_pdf_parser(filename, binary=None, **_kwargs):
        assert filename.endswith(".pdf")
        assert binary == b"pdf-bytes"
        return [("WPS PDF text", None)], [], None

    monkeypatch.setattr(naive, "convert_office_to_docx", fake_docx_convert, raising=False)
    monkeypatch.setattr(naive, "convert_office_to_pdf", fake_pdf_convert, raising=False)
    monkeypatch.setitem(naive.PARSERS, "deepdoc", fake_pdf_parser)

    chunks = naive.chunk(
        "demo.wps",
        binary=b"wps-bytes",
        callback=lambda *_args, **_kwargs: None,
        parser_config={"layout_recognize": "DeepDOC", "chunk_token_num": 128, "delimiter": "\n"},
    )

    assert chunks == [{"content_with_weight": "WPS PDF text"}]


def test_general_parser_falls_back_to_tika_when_wps_office_conversions_fail(monkeypatch):
    naive = load_naive(monkeypatch)

    def fake_docx_convert(_binary, _suffix):
        raise FileNotFoundError("DOCX file not found after conversion")

    def fake_pdf_convert(_binary, _suffix):
        raise FileNotFoundError("PDF file not found after conversion")

    monkeypatch.setattr(naive, "convert_office_to_docx", fake_docx_convert, raising=False)
    monkeypatch.setattr(naive, "convert_office_to_pdf", fake_pdf_convert, raising=False)
    monkeypatch.setattr(naive, "parse_office_with_tika", lambda _binary, _filename, _callback: [("WPS Tika text", "")], raising=False)

    chunks = naive.chunk(
        "demo.wps",
        binary=b"wps-bytes",
        callback=lambda *_args, **_kwargs: None,
        parser_config={"chunk_token_num": 128, "delimiter": "\n"},
    )

    assert chunks == [{"content_with_weight": "WPS Tika text"}]


def test_general_parser_skips_unsupported_embedded_bin_files(monkeypatch):
    naive = load_naive(monkeypatch)
    progress = []

    class FakeDocx:
        def __call__(self, filename, binary=None):
            return [("Main text", None)], []

    monkeypatch.setattr(naive, "extract_embed_file", lambda _binary: [("unknown.bin", b"embedded")])
    monkeypatch.setattr(naive, "Docx", FakeDocx)

    chunks = naive.chunk("demo.docx", binary=b"docx-bytes", callback=lambda *args, **_kwargs: progress.append(args))

    assert chunks == [{"content_with_weight": "Main text"}]
    assert not any("Failed to chunk embed" in str(item) for item in progress)


def test_general_parser_routes_ole_docx_to_existing_doc_parser(monkeypatch):
    naive = load_naive(monkeypatch)
    ole_binary = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy-word-data"
    parsed = []

    def from_buffer(stream):
        parsed.append(stream.read())
        return {"content": "Legacy DOC text\n"}

    tika_module = types.ModuleType("tika")
    tika_module.parser = type("Parser", (), {"from_buffer": staticmethod(from_buffer)})
    monkeypatch.setitem(sys.modules, "tika", tika_module)

    class UnexpectedDocxParser:
        def __call__(self, *_args, **_kwargs):
            raise AssertionError("OLE content must not reach the DOCX parser")

    monkeypatch.setattr(naive, "Docx", UnexpectedDocxParser)

    chunks = naive.chunk(
        "legacy.docx",
        binary=ole_binary,
        callback=lambda *_args, **_kwargs: None,
        parser_config={"chunk_token_num": 128, "delimiter": "\n"},
    )

    assert parsed == [ole_binary]
    assert chunks == [{"content_with_weight": "Legacy DOC text"}]
