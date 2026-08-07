import importlib.util
import sys
import types
from pathlib import Path


def load_file_utils(monkeypatch):
    class Value:
        def __init__(self, value):
            self.value = value

    stub_modules = {
        "api": {},
        "api.constants": {"IMG_BASE64_PREFIX": "data:image/png;base64,"},
        "api.db": {
            "FileType": type(
                "FileType",
                (),
                {
                    "PDF": Value("pdf"),
                    "DOC": Value("doc"),
                    "AURAL": Value("aural"),
                    "VISUAL": Value("visual"),
                    "OTHER": Value("other"),
                },
            )
        },
        "deepdoc": {},
        "deepdoc.parser": {"PptParser": object},
        "pdfplumber": {},
        "PIL": {},
        "PIL.Image": {},
    }
    for name, attrs in stub_modules.items():
        module = types.ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(module, attr_name, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_path = Path(__file__).parents[3] / "api" / "utils" / "file_utils.py"
    spec = importlib.util.spec_from_file_location("file_utils_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_file_service(monkeypatch):
    class FileType:
        VISUAL = "visual"
        AURAL = "aural"
        FOLDER = type("Value", (), {"value": "folder"})

    class ParserType:
        PICTURE = type("Value", (), {"value": "picture"})
        AUDIO = type("Value", (), {"value": "audio"})
        PRESENTATION = type("Value", (), {"value": "presentation"})
        EMAIL = type("Value", (), {"value": "email"})

    stub_modules = {
        "api": {},
        "api.db": {
            "FileType": FileType,
            "KNOWLEDGEBASE_FOLDER_NAME": "knowledgebase",
            "DB": type("DB", (), {"connection_context": staticmethod(lambda: lambda fn: fn)}),
        },
        "api.db.db_models": {
            "DB": type("DB", (), {"connection_context": staticmethod(lambda: lambda fn: fn)}),
            "Document": object,
            "File": object,
            "File2Document": object,
            "Knowledgebase": object,
            "Task": object,
        },
        "api.db.services.common_service": {"CommonService": object},
        "api.db.services.knowledgebase_service": {"KnowledgebaseService": object},
        "api.db.services": {"duplicate_name": lambda *args, **kwargs: "name"},
        "api.db.services.document_service": {"DocumentService": object},
        "api.db.services.file2document_service": {"File2DocumentService": object},
        "api.db.services.task_service": {"TaskService": object},
        "api.utils": {},
        "api.utils.file_utils": {
            "filename_type": lambda *_args, **_kwargs: "doc",
            "read_potential_broken_pdf": lambda value: value,
            "thumbnail_img": lambda *_args, **_kwargs: None,
            "sanitize_path": lambda value: value,
        },
        "api.apps": {"current_user": None},
        "common": {},
        "common.settings": {"STORAGE_IMPL": object()},
        "common.constants": {"TaskStatus": object, "FileSource": object, "ParserType": ParserType},
        "peewee": {"fn": object},
        "rag": {},
        "rag.llm": {},
        "rag.llm.chat_model": {"GptV4": object},
        "rag.llm.cv_model": {"GptV4": object},
        "common.misc_utils": {"get_uuid": lambda: "id"},
    }
    for name, attrs in stub_modules.items():
        module = types.ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(module, attr_name, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_path = Path(__file__).parents[3] / "api" / "db" / "services" / "file_service.py"
    spec = importlib.util.spec_from_file_location("file_service_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dps_is_recognized_as_document_file_type(monkeypatch):
    file_utils = load_file_utils(monkeypatch)

    assert file_utils.filename_type("demo.dps") == "doc"


def test_dps_routes_to_presentation_parser(monkeypatch):
    file_service = load_file_service(monkeypatch)

    parser = file_service.FileService.get_parser("doc", "demo.dps", "naive")

    assert parser == "presentation"
