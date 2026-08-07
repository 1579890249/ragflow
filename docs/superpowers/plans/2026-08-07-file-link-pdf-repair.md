# 文件链接阶段 PDF 修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文件管理中的异常 PDF 链接到知识库前，原位修复存储对象并同步文件大小，避免 0 页导致空任务列表异常。

**Architecture:** 在 `FileService` 中增加可独立测试的 `repair_pdf_if_needed()`，集中处理类型判断、读取、修复、写回和大小同步。`/file2document/convert` 在删除旧关联前调用该方法一次，随后使用返回文件对象的最新大小创建全部目标知识库文档。

**Tech Stack:** Python 3.12、Peewee、Quart、pytest、RAGFlow Storage API、现有 `read_potential_broken_pdf()`。

---

## 文件结构

- 新建：`test/unit_test/api/db/services/test_file_service_pdf_repair.py`，覆盖修复服务的存储和数据库行为。
- 新建：`test/unit_test/api/test_file2document_app.py`，覆盖链接流程的调用顺序和文档大小传递。
- 修改：`api/db/services/file_service.py`，增加 `repair_pdf_if_needed()`。
- 修改：`api/apps/file2document_app.py`，在删除旧关联前修复文件，并移除知识库循环内的重复文件查询。

### Task 1：定义 PDF 原位修复服务行为

**Files:**
- Create: `test/unit_test/api/db/services/test_file_service_pdf_repair.py`
- Modify: `api/db/services/file_service.py`

- [ ] **Step 1：编写修复、跳过和失败传播测试**

```python
from types import SimpleNamespace

import pytest

from api.db import FileType
from api.db.services import file_service as file_service_module
from api.db.services.file_service import FileService


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


def pdf_file(size=8):
    return SimpleNamespace(
        id="file-id",
        parent_id="folder-id",
        location="source.pdf",
        type=FileType.PDF.value,
        size=size,
    )


def test_repair_pdf_if_needed_overwrites_changed_bytes_and_updates_size(monkeypatch):
    file = pdf_file()
    storage = RecordingStorage()
    updates = []
    monkeypatch.setattr(file_service_module, "read_potential_broken_pdf", lambda _blob: b"repaired-pdf")
    monkeypatch.setattr(FileService, "update_by_id", lambda file_id, values: updates.append((file_id, values)) or 1)

    result = FileService.repair_pdf_if_needed(file, storage_impl=storage)

    assert result is file
    assert file.size == len(b"repaired-pdf")
    assert storage.calls == [
        ("get", "folder-id", "source.pdf"),
        ("put", "folder-id", "source.pdf", b"repaired-pdf"),
    ]
    assert updates == [("file-id", {"size": len(b"repaired-pdf")})]


def test_repair_pdf_if_needed_does_not_write_unchanged_pdf(monkeypatch):
    file = pdf_file(size=8)
    storage = RecordingStorage(blob=b"original")
    monkeypatch.setattr(file_service_module, "read_potential_broken_pdf", lambda blob: blob)
    monkeypatch.setattr(FileService, "update_by_id", lambda *_args: pytest.fail("database update must not run"))

    result = FileService.repair_pdf_if_needed(file, storage_impl=storage)

    assert result is file
    assert file.size == 8
    assert storage.calls == [("get", "folder-id", "source.pdf")]


def test_repair_pdf_if_needed_skips_non_pdf(monkeypatch):
    file = SimpleNamespace(type=FileType.DOC.value)
    storage = RecordingStorage()
    monkeypatch.setattr(file_service_module, "read_potential_broken_pdf", lambda _blob: pytest.fail("repair must not run"))

    assert FileService.repair_pdf_if_needed(file, storage_impl=storage) is file
    assert storage.calls == []


def test_repair_pdf_if_needed_propagates_storage_write_error(monkeypatch):
    file = pdf_file()
    storage = RecordingStorage(put_error=RuntimeError("storage unavailable"))
    monkeypatch.setattr(file_service_module, "read_potential_broken_pdf", lambda _blob: b"repaired-pdf")
    monkeypatch.setattr(FileService, "update_by_id", lambda *_args: pytest.fail("database update must not run"))

    with pytest.raises(RuntimeError, match="storage unavailable"):
        FileService.repair_pdf_if_needed(file, storage_impl=storage)
```

- [ ] **Step 2：运行测试并确认 RED**

Run:

```powershell
venv\Scripts\python.exe -m pytest test/unit_test/api/db/services/test_file_service_pdf_repair.py -q
```

Expected: FAIL，提示 `FileService` 不存在 `repair_pdf_if_needed`。

- [ ] **Step 3：实现最小服务方法**

在 `FileService` 中加入：

```python
    @classmethod
    def repair_pdf_if_needed(cls, file, storage_impl=None):
        if file.type != FileType.PDF.value:
            return file

        if storage_impl is None:
            storage_impl = settings.STORAGE_IMPL

        blob = storage_impl.get(file.parent_id, file.location)
        repaired_blob = read_potential_broken_pdf(blob)
        if repaired_blob == blob:
            return file

        storage_impl.put(file.parent_id, file.location, repaired_blob)
        repaired_size = len(repaired_blob)
        if not cls.update_by_id(file.id, {"size": repaired_size}):
            raise RuntimeError("Database error (File size update)!")
        file.size = repaired_size
        return file
```

- [ ] **Step 4：运行测试并确认 GREEN**

Run:

```powershell
venv\Scripts\python.exe -m pytest test/unit_test/api/db/services/test_file_service_pdf_repair.py -q
```

Expected: 4 passed。

### Task 2：把修复接入链接流程

**Files:**
- Create: `test/unit_test/api/test_file2document_app.py`
- Modify: `api/apps/file2document_app.py`

- [ ] **Step 1：编写链接顺序与修复后大小测试**

测试使用无副作用的模块桩加载 `file2document_app.py`，并让服务调用记录事件。核心断言如下：

```python
async def test_convert_repairs_before_removing_links_and_uses_repaired_size(app_module, service_state):
    result = await app_module.convert()

    assert service_state.events.index("repair") < service_state.events.index("read-existing-links")
    assert service_state.inserted_document["size"] == len(b"repaired-pdf")
    assert result == {"data": [{"document_id": "document-id"}]}


async def test_convert_keeps_existing_links_when_repair_fails(app_module, service_state):
    service_state.repair_error = RuntimeError("repair failed")

    result = await app_module.convert()

    assert result == {"error": "repair failed"}
    assert "read-existing-links" not in service_state.events
    assert service_state.inserted_document is None
```

桩模块必须提供实际源码引用的 `manager.route`、`login_required`、
`validate_request`、`get_request_json`、`FileService`、
`File2DocumentService`、`KnowledgebaseService`、`DocumentService` 和
`current_user.id`；除存储/数据库边界外，不模拟 `repair_pdf_if_needed()` 的内部行为。

- [ ] **Step 2：运行链接测试并确认 RED**

Run:

```powershell
venv\Scripts\python.exe -m pytest test/unit_test/api/test_file2document_app.py -q
```

Expected: FAIL；当前流程未调用 `repair_pdf_if_needed()`，文档大小仍为原始大小，修复失败也不会阻止删除旧关联。

- [ ] **Step 3：调整链接流程**

在 `for id in file_ids_list` 起始处加入一次文件查询和修复：

```python
                e, file = FileService.get_by_id(id)
                if not e:
                    return get_data_error_result(message="Can't find this file!")
                file = FileService.repair_pdf_if_needed(file)

                informs = File2DocumentService.get_by_file_id(id)
```

删除 `for kb_id in kb_ids` 中现有的重复 `FileService.get_by_id(id)` 块。后续
`DocumentService.insert()` 继续使用 `file.size`，该值已经同步为修复后大小。

- [ ] **Step 4：运行链接测试并确认 GREEN**

Run:

```powershell
venv\Scripts\python.exe -m pytest test/unit_test/api/test_file2document_app.py -q
```

Expected: 2 passed。

### Task 3：回归和真实 PDF 验证

**Files:**
- Test: `test/unit_test/api/db/services/test_file_service_pdf_repair.py`
- Test: `test/unit_test/api/test_file2document_app.py`
- Test: `test/unit_test/api/db/services/test_file_service_list.py`
- Test: `test/unit_test/api/db/services/test_file_service_move.py`

- [ ] **Step 1：运行文件服务定向测试**

```powershell
venv\Scripts\python.exe -m pytest test/unit_test/api/db/services/test_file_service_pdf_repair.py test/unit_test/api/test_file2document_app.py test/unit_test/api/db/services/test_file_service_list.py test/unit_test/api/db/services/test_file_service_move.py -q
```

Expected: 全部通过。

- [ ] **Step 2：运行 Ruff 和编译检查**

```powershell
venv\Scripts\python.exe -m ruff check api/db/services/file_service.py api/apps/file2document_app.py test/unit_test/api/db/services/test_file_service_pdf_repair.py test/unit_test/api/test_file2document_app.py
venv\Scripts\python.exe -m compileall -q api/db/services/file_service.py api/apps/file2document_app.py test/unit_test/api/db/services/test_file_service_pdf_repair.py test/unit_test/api/test_file2document_app.py
```

Expected: 两个命令退出码均为 0。

- [ ] **Step 3：在公司环境的同版本容器中验证真实异常 PDF**

将 `E:\temp\风神轮胎\问答测试.pdf` 作为临时输入，仅调用新增服务所复用的修复逻辑，确认修复前 pdfplumber 为 0 页、修复后为 15 页；不覆盖线上业务对象。

Expected: 修复后的 PDF 为 15 页，临时文件验证后清理。

- [ ] **Step 4：检查最终差异**

```powershell
git diff --check
git diff -- api/db/services/file_service.py api/apps/file2document_app.py test/unit_test/api/db/services/test_file_service_pdf_repair.py test/unit_test/api/test_file2document_app.py
```

Expected: 无空白错误，差异仅包含本计划定义的修复和测试；`file_service.py` 中已有的其他用户改动保持不变。

由于 `api/db/services/file_service.py` 当前包含与本任务无关的用户改动，本计划不自动提交生产代码，避免把其他改动混入提交。实施结果保留在工作区供用户统一审阅和提交。
