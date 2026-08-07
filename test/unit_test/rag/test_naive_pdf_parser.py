import sys
import types
import importlib.util
from pathlib import Path


def test_pdf_parser_uses_public_images_hook(monkeypatch):
    class FakePdfParser:
        def __init__(self):
            self.boxes = [{"text": "content"}]

        def __images__(self, *args):
            self.images_args = args
            return 2

        def _layouts_rec(self, zoomin):
            self.layout_zoomin = zoomin

        def _table_transformer_job(self, zoomin):
            self.table_zoomin = zoomin

        def _text_merge(self, zoomin=None):
            self.text_merge_zoomin = zoomin

        def _extract_table_figure(self, *args):
            return []

        def _naive_vertical_merge(self):
            pass

        def _concat_downward(self):
            pass

        def _line_tag(self, box, zoomin):
            return f"@@{zoomin}##"

    stub_modules = {
        "api.db.services.llm_service": {"LLMBundle": object},
        "common.constants": {"LLMType": object},
        "common.parser_config_utils": {"normalize_layout_recognizer": lambda value: (value, None)},
        "common.token_utils": {"num_tokens_from_string": lambda text: len(text.split())},
        "deepdoc.parser": {
            "DocxParser": object,
            "ExcelParser": object,
            "HtmlParser": object,
            "JsonParser": object,
            "MarkdownElementExtractor": object,
            "MarkdownParser": object,
            "PdfParser": FakePdfParser,
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
        "docx": {"Document": object},
        "docx.image.exceptions": {
            "InvalidImageStreamError": Exception,
            "UnexpectedEndOfFileError": Exception,
            "UnrecognizedImageError": Exception,
        },
        "docx.opc.oxml": {"parse_xml": lambda xml: None},
        "docx.opc.pkgreader": {
            "_SerializedRelationship": object,
            "_SerializedRelationships": type("_SerializedRelationships", (), {"load_from_xml": None}),
        },
        "markdown": {"markdown": lambda text, *args, **kwargs: text},
        "PIL": {},
        "PIL.Image": {"open": lambda *args, **kwargs: None},
        "rag.nlp": {
            "append_context2table_image4pdf": lambda sections, tables, image_context_size: tables,
            "concat_img": lambda left, right: left or right,
            "find_codec": lambda binary: "utf-8",
            "naive_merge": lambda *args, **kwargs: [],
            "naive_merge_docx": lambda *args, **kwargs: ([], []),
            "naive_merge_with_images": lambda *args, **kwargs: ([], []),
            "rag_tokenizer": type("Tokenizer", (), {"tokenize": staticmethod(lambda text: text), "fine_grained_tokenize": staticmethod(lambda text: text)}),
            "tokenize_chunks": lambda *args, **kwargs: [],
            "tokenize_chunks_with_images": lambda *args, **kwargs: [],
            "tokenize_table": lambda *args, **kwargs: [],
            "attach_media_context": lambda *args, **kwargs: None,
        },
        "rag.utils.file_utils": {
            "extract_embed_file": lambda binary: [],
            "extract_html": lambda url: (None, None),
            "extract_links_from_docx": lambda binary: [],
            "extract_links_from_pdf": lambda binary: [],
        },
    }

    for name, attrs in stub_modules.items():
        module = types.ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(module, attr_name, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_path = Path(__file__).parents[3] / "rag" / "app" / "naive.py"
    spec = importlib.util.spec_from_file_location("naive_under_test", module_path)
    naive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(naive)
    Pdf = naive.Pdf

    parser = Pdf()
    sections, tables = parser(
        "sample.pdf",
        from_page=1,
        to_page=3,
        zoomin=3,
        callback=lambda *args, **kwargs: None,
    )

    assert parser.images_args[:4] == ("sample.pdf", 3, 1, 3)
    assert parser.layout_zoomin == 2
    assert parser.table_zoomin == 2
    assert parser.text_merge_zoomin == 2
    assert sections == [("content", "@@2##")]
    assert tables == []
