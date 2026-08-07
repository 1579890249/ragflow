import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_file_service(monkeypatch):
    class Value:
        def __init__(self, value):
            self.value = value

    class FileType:
        PDF = Value("pdf")
        DOC = Value("doc")
        FOLDER = Value("folder")
        OTHER = Value("other")
        VISUAL = "visual"
        AURAL = "aural"

    class Database:
        @staticmethod
        def connection_context():
            return lambda function: function

    class CommonService:
        @classmethod
        def update_by_id(cls, _file_id, _values):
            raise AssertionError("unexpected database update")

    stub_modules = {
        "api": {},
        "api.db": {"FileType": FileType, "KNOWLEDGEBASE_FOLDER_NAME": "knowledgebase"},
        "api.db.db_models": {
            "DB": Database,
            "Document": object,
            "File": object,
            "File2Document": object,
            "Knowledgebase": object,
            "Task": object,
        },
        "api.db.services": {"duplicate_name": lambda *args, **kwargs: "name"},
        "api.db.services.common_service": {"CommonService": CommonService},
        "api.db.services.document_service": {"DocumentService": object},
        "api.db.services.file2document_service": {"File2DocumentService": object},
        "api.db.services.knowledgebase_service": {"KnowledgebaseService": object},
        "api.db.services.task_service": {"TaskService": object},
        "api.utils": {},
        "api.utils.file_utils": {
            "filename_type": lambda *_args, **_kwargs: "doc",
            "read_potential_broken_pdf": lambda value: value,
            "thumbnail_img": lambda *_args, **_kwargs: None,
            "sanitize_path": lambda value: value,
        },
        "common": {},
        "common.settings": {"STORAGE_IMPL": object()},
        "common.constants": {
            "TaskStatus": object,
            "FileSource": object,
            "ParserType": object,
        },
        "common.misc_utils": {"get_uuid": lambda: "id"},
        "peewee": {"fn": object},
        "rag": {},
        "rag.llm": {},
        "rag.llm.cv_model": {"GptV4": object},
    }
    for name, attrs in stub_modules.items():
        module = types.ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(module, attr_name, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_path = REPO_ROOT / "api" / "db" / "services" / "file_service.py"
    spec = importlib.util.spec_from_file_location("file_service_pdf_repair_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingStorage:
    def __init__(self, blob=b"original", put_error=None):
        self.blob = blob
        self.put_error = put_error
        self.calls = []

    def get(self, bucket, location):
        self.calls.append(("get", bucket, location))
        return self.blob

    def put(self, bucket, location, blob):
        self.calls.append(("put", bucket, location, blob))
        if self.put_error:
            raise self.put_error


def pdf_file(file_type, size=8):
    return SimpleNamespace(
        id="file-id",
        parent_id="folder-id",
        location="source.pdf",
        type=file_type,
        size=size,
    )


def test_repair_pdf_if_needed_overwrites_changed_bytes_and_updates_size(monkeypatch):
    module = load_file_service(monkeypatch)
    service = module.FileService
    file = pdf_file(module.FileType.PDF.value)
    storage = RecordingStorage()
    updates = []
    monkeypatch.setattr(module, "read_potential_broken_pdf", lambda _blob: b"repaired-pdf")
    monkeypatch.setattr(service, "update_by_id", lambda file_id, values: updates.append((file_id, values)) or 1)

    result = service.repair_pdf_if_needed(file, storage_impl=storage)

    assert result is file
    assert file.size == len(b"repaired-pdf")
    assert storage.calls == [
        ("get", "folder-id", "source.pdf"),
        ("put", "folder-id", "source.pdf", b"repaired-pdf"),
    ]
    assert updates == [("file-id", {"size": len(b"repaired-pdf")})]


def test_repair_pdf_if_needed_does_not_write_unchanged_pdf(monkeypatch):
    module = load_file_service(monkeypatch)
    service = module.FileService
    file = pdf_file(module.FileType.PDF.value)
    storage = RecordingStorage()
    monkeypatch.setattr(module, "read_potential_broken_pdf", lambda blob: blob)

    result = service.repair_pdf_if_needed(file, storage_impl=storage)

    assert result is file
    assert file.size == 8
    assert storage.calls == [("get", "folder-id", "source.pdf")]


def test_repair_pdf_if_needed_reconciles_size_after_a_partial_previous_attempt(monkeypatch):
    module = load_file_service(monkeypatch)
    service = module.FileService
    file = pdf_file(module.FileType.PDF.value, size=99)
    storage = RecordingStorage()
    updates = []
    monkeypatch.setattr(module, "read_potential_broken_pdf", lambda blob: blob)
    monkeypatch.setattr(service, "update_by_id", lambda file_id, values: updates.append((file_id, values)) or 1)

    result = service.repair_pdf_if_needed(file, storage_impl=storage)

    assert result is file
    assert file.size == len(b"original")
    assert storage.calls == [("get", "folder-id", "source.pdf")]
    assert updates == [("file-id", {"size": len(b"original")})]


def test_repair_pdf_if_needed_skips_non_pdf(monkeypatch):
    module = load_file_service(monkeypatch)
    service = module.FileService
    file = SimpleNamespace(type=module.FileType.DOC.value)
    storage = RecordingStorage()
    monkeypatch.setattr(module, "read_potential_broken_pdf", lambda _blob: pytest.fail("repair must not run"))

    assert service.repair_pdf_if_needed(file, storage_impl=storage) is file
    assert storage.calls == []


def test_repair_pdf_if_needed_propagates_storage_write_error(monkeypatch):
    module = load_file_service(monkeypatch)
    service = module.FileService
    file = pdf_file(module.FileType.PDF.value)
    storage = RecordingStorage(put_error=RuntimeError("storage unavailable"))
    monkeypatch.setattr(module, "read_potential_broken_pdf", lambda _blob: b"repaired-pdf")

    with pytest.raises(RuntimeError, match="storage unavailable"):
        service.repair_pdf_if_needed(file, storage_impl=storage)
