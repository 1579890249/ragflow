from types import SimpleNamespace

from api.db import FileType
from api.db.services.file_service import FileService


def test_move_folder_without_existing_target_keeps_folder_id(monkeypatch):
    source_folder = SimpleNamespace(id="source-folder", name="docs", type=FileType.FOLDER.value)
    dest_folder = SimpleNamespace(id="dest-folder")
    calls = []

    monkeypatch.setattr(FileService, "query", lambda **kwargs: [])
    monkeypatch.setattr(
        FileService,
        "update_by_id",
        lambda file_id, values: calls.append(("update", file_id, values)) or True,
    )
    monkeypatch.setattr(
        FileService,
        "list_all_files_by_parent_id",
        lambda parent_id: calls.append(("list_children", parent_id)) or [],
    )
    monkeypatch.setattr(
        FileService,
        "delete_by_id",
        lambda file_id: calls.append(("delete", file_id)) or True,
    )

    FileService.move_entry_recursive(source_folder, dest_folder, storage_impl=SimpleNamespace())

    assert calls == [("update", "source-folder", {"parent_id": "dest-folder"})]
