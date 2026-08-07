import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]


def load_file_service(monkeypatch):
    class FileType:
        FOLDER = type("Value", (), {"value": "folder"})

    class Database:
        @staticmethod
        def connection_context():
            return lambda function: function

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
        "api.db.services.common_service": {"CommonService": object},
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
    spec = importlib.util.spec_from_file_location("file_service_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Field:
    def __init__(self, name):
        self.name = name

    def __eq__(self, _other):
        return Condition(self.name, _other)

    def __invert__(self):
        return self

    def asc(self):
        return self

    def desc(self):
        return self


class Condition:
    def __init__(self, field_name, value):
        self.field_name = field_name
        self.value = value

    def __invert__(self):
        return self


class PageQuery:
    def __init__(self, rows):
        self.rows = rows

    def where(self, *_conditions):
        return self

    def count(self):
        return len(self.rows)

    def order_by(self, _field):
        return self

    def paginate(self, _page_number, _items_per_page):
        return self

    def dicts(self):
        return iter(self.rows)


class SnapshotQuery:
    def __init__(self, rows):
        self.rows = rows
        self.used_tuples = False
        self.used_iterator = False
        self.conditions = []

    def where(self, *conditions):
        self.conditions.extend(conditions)
        return self

    def tuples(self):
        self.used_tuples = True
        return self

    def iterator(self):
        self.used_iterator = True
        return iter(self.rows)


class FileModel:
    id = Field("id")
    parent_id = Field("parent_id")
    tenant_id = Field("tenant_id")
    name = Field("name")
    size = Field("size")
    type = Field("type")

    page_rows = [
        {"id": "folder", "name": "docs", "type": "folder", "size": 999},
        {"id": "file", "name": "readme.pdf", "type": "pdf", "size": 12},
    ]
    snapshot_rows = [
        ("folder", "root", 999, "folder"),
        ("child-folder", "folder", 3, "folder"),
        ("nested-file", "child-folder", 5, "doc"),
        ("file", "root", 12, "pdf"),
    ]
    select_calls = []
    snapshot_query = None

    @classmethod
    def getter_by(cls, field_name):
        return getattr(cls, field_name)

    @classmethod
    def select(cls, *fields):
        cls.select_calls.append(tuple(field.name for field in fields))
        if not fields:
            return PageQuery(cls.page_rows)

        cls.snapshot_query = SnapshotQuery(cls.snapshot_rows)
        return cls.snapshot_query


def test_calculates_sizes_for_multiple_nested_folders(monkeypatch):
    service = load_file_service(monkeypatch).FileService
    rows = [
        ("root-a", "root-a", 100, "folder"),
        ("file-a", "root-a", 10, "pdf"),
        ("folder-a", "root-a", 3, "folder"),
        ("nested-file", "folder-a", 5, "doc"),
        ("root-b", "root-b", 200, "folder"),
    ]

    folder_sizes, has_child_folders = service._calculate_folder_metrics(
        rows, ["root-a", "folder-a", "root-b"]
    )

    assert folder_sizes == {"root-a": 18, "folder-a": 5, "root-b": 0}
    assert has_child_folders == {"root-a": True, "folder-a": False, "root-b": False}


def test_does_not_traverse_children_of_non_folder_rows(monkeypatch):
    service = load_file_service(monkeypatch).FileService
    rows = [
        ("root", "root", 0, "folder"),
        ("file", "root", 7, "pdf"),
        ("unreachable-folder", "file", 11, "folder"),
        ("unreachable-file", "unreachable-folder", 13, "doc"),
    ]

    folder_sizes, has_child_folders = service._calculate_folder_metrics(rows, ["root"])

    assert folder_sizes == {"root": 7}
    assert has_child_folders == {"root": False}


def test_cycles_terminate_without_counting_a_row_twice(monkeypatch):
    service = load_file_service(monkeypatch).FileService
    rows = [
        ("folder-a", "folder-b", 2, "folder"),
        ("folder-b", "folder-a", 3, "folder"),
        ("file", "folder-b", 5, "pdf"),
    ]
    repeated_nodes = []

    folder_sizes, has_child_folders = service._calculate_folder_metrics(
        rows,
        ["folder-a"],
        on_cycle=lambda root_id, repeated_id: repeated_nodes.append((root_id, repeated_id)),
    )

    assert folder_sizes == {"folder-a": 8}
    assert has_child_folders == {"folder-a": True}
    assert repeated_nodes == [("folder-a", "folder-a")]


def test_get_by_pf_id_calculates_folder_metrics_from_one_tenant_snapshot(monkeypatch):
    module = load_file_service(monkeypatch)
    service = module.FileService
    service.model = FileModel
    FileModel.select_calls = []
    FileModel.snapshot_query = None

    monkeypatch.setattr(
        service,
        "get_folder_size",
        lambda _folder_id: (_ for _ in ()).throw(AssertionError("legacy per-folder query was used")),
    )
    monkeypatch.setattr(service, "get_kb_id_by_file_id", lambda file_id: [{"file_id": file_id}])

    files, count = service.get_by_pf_id("tenant", "root", 1, 50, "name", False, "")

    assert count == 2
    assert files == [
        {
            "id": "folder",
            "name": "docs",
            "type": "folder",
            "size": 8,
            "kbs_info": [],
            "has_child_folder": True,
        },
        {
            "id": "file",
            "name": "readme.pdf",
            "type": "pdf",
            "size": 12,
            "kbs_info": [{"file_id": "file"}],
        },
    ]
    assert FileModel.select_calls == [(), ("id", "parent_id", "size", "type")]
    assert [(condition.field_name, condition.value) for condition in FileModel.snapshot_query.conditions] == [
        ("tenant_id", "tenant")
    ]
    assert FileModel.snapshot_query.used_tuples is True
    assert FileModel.snapshot_query.used_iterator is True


def test_get_by_pf_id_skips_tenant_snapshot_when_page_has_no_folders(monkeypatch):
    module = load_file_service(monkeypatch)
    service = module.FileService
    service.model = FileModel
    monkeypatch.setattr(
        FileModel,
        "page_rows",
        [{"id": "file", "name": "readme.pdf", "type": "pdf", "size": 12}],
    )
    FileModel.select_calls = []
    FileModel.snapshot_query = None

    monkeypatch.setattr(
        service,
        "get_folder_size",
        lambda _folder_id: (_ for _ in ()).throw(AssertionError("legacy per-folder query was used")),
    )
    monkeypatch.setattr(service, "get_kb_id_by_file_id", lambda file_id: [{"file_id": file_id}])

    files, count = service.get_by_pf_id("tenant", "root", 1, 50, "name", False, "")

    assert count == 1
    assert files == [
        {
            "id": "file",
            "name": "readme.pdf",
            "type": "pdf",
            "size": 12,
            "kbs_info": [{"file_id": "file"}],
        }
    ]
    assert FileModel.select_calls == [()]
    assert FileModel.snapshot_query is None
