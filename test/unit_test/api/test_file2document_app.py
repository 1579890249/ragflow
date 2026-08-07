import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]


class ServiceState:
    def __init__(self):
        self.events = []
        self.repair_error = None
        self.inserted_documents = []
        self.file = SimpleNamespace(
            id="file-id",
            type="pdf",
            name="source.pdf",
            location="source.pdf",
            size=len(b"original"),
        )


def load_file2document_app(monkeypatch):
    state = ServiceState()

    class Value:
        def __init__(self, value):
            self.value = value

    class FileType:
        FOLDER = Value("folder")

    class FileService:
        @classmethod
        def get_by_ids(cls, _file_ids):
            return [state.file]

        @classmethod
        def get_all_innermost_file_ids(cls, _file_id, _accumulator):
            return [state.file.id]

        @classmethod
        def get_by_id(cls, _file_id):
            state.events.append("load-file")
            return True, state.file

        @classmethod
        def repair_pdf_if_needed(cls, file):
            state.events.append("repair")
            if state.repair_error:
                raise state.repair_error
            file.size = len(b"repaired-pdf")
            return file

    class File2DocumentService:
        @classmethod
        def get_by_file_id(cls, _file_id):
            state.events.append("read-existing-links")
            return [SimpleNamespace(document_id="old-document-id")]

        @classmethod
        def delete_by_file_id(cls, _file_id):
            state.events.append("delete-existing-links")

        @classmethod
        def insert(cls, values):
            document_id = values["document_id"]
            return SimpleNamespace(to_json=lambda: {"document_id": document_id})

    class DocumentService:
        @classmethod
        def get_by_id(cls, document_id):
            return True, SimpleNamespace(id=document_id)

        @classmethod
        def get_tenant_id(cls, _document_id):
            return "tenant-id"

        @classmethod
        def remove_document(cls, _document, _tenant_id):
            state.events.append("remove-existing-document")
            return True

        @classmethod
        def insert(cls, values):
            state.inserted_documents.append(values)
            return SimpleNamespace(id=values["id"])

    class KnowledgebaseService:
        @classmethod
        def get_by_id(cls, kb_id):
            return True, SimpleNamespace(
                id=kb_id,
                parser_id="naive",
                pipeline_id=None,
                parser_config={},
            )

    async def get_request_json():
        return {"file_ids": [state.file.id], "kb_ids": ["kb-a", "kb-b"]}

    def identity_decorator(function):
        return function

    class RouteManager:
        @staticmethod
        def route(*_args, **_kwargs):
            return identity_decorator

    uuid_values = iter(["new-document-a", "new-link-a", "new-document-b", "new-link-b"])
    stub_modules = {
        "api": {},
        "api.apps": {
            "login_required": identity_decorator,
            "current_user": SimpleNamespace(id="user-id"),
        },
        "api.db": {"FileType": FileType},
        "api.db.services": {},
        "api.db.services.document_service": {"DocumentService": DocumentService},
        "api.db.services.file2document_service": {"File2DocumentService": File2DocumentService},
        "api.db.services.file_service": {"FileService": FileService},
        "api.db.services.knowledgebase_service": {"KnowledgebaseService": KnowledgebaseService},
        "api.utils": {},
        "api.utils.api_utils": {
            "get_data_error_result": lambda **kwargs: {"error": kwargs["message"]},
            "get_json_result": lambda **kwargs: kwargs,
            "get_request_json": get_request_json,
            "server_error_response": lambda error: {"error": str(error)},
            "validate_request": lambda *_args: identity_decorator,
        },
        "common": {},
        "common.constants": {"RetCode": object},
        "common.misc_utils": {"get_uuid": lambda: next(uuid_values)},
    }
    for name, attrs in stub_modules.items():
        module = types.ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(module, attr_name, value)
        monkeypatch.setitem(sys.modules, name, module)

    module_path = REPO_ROOT / "api" / "apps" / "file2document_app.py"
    spec = importlib.util.spec_from_file_location("file2document_app_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    module.manager = RouteManager()
    spec.loader.exec_module(module)
    return module, state


def test_convert_repairs_before_removing_links_and_uses_repaired_size(monkeypatch):
    module, state = load_file2document_app(monkeypatch)

    result = asyncio.run(module.convert())

    assert state.events.count("repair") == 1
    assert state.events.index("repair") < state.events.index("read-existing-links")
    assert [document["size"] for document in state.inserted_documents] == [
        len(b"repaired-pdf"),
        len(b"repaired-pdf"),
    ]
    assert result == {
        "data": [
            {"document_id": "new-document-a"},
            {"document_id": "new-document-b"},
        ]
    }


def test_convert_keeps_existing_links_when_repair_fails(monkeypatch):
    module, state = load_file2document_app(monkeypatch)
    state.repair_error = RuntimeError("repair failed")

    result = asyncio.run(module.convert())

    assert result == {"error": "repair failed"}
    assert state.events == ["load-file", "repair"]
    assert state.inserted_documents == []
