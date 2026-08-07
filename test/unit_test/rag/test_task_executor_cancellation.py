import ast
import asyncio
import copy
import json
import logging
import types
from datetime import datetime
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


class DoesNotExist(Exception):
    pass


class TaskCanceledException(Exception):
    pass


def load_function(name, namespace):
    source_path = REPO_ROOT / "rag" / "svr" / "task_executor.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        (
            node
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )
    assert function is not None, f"{name} must exist"
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace[name]


def load_task_service_function(name, namespace):
    source_path = REPO_ROOT / "api" / "db" / "services" / "task_service.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        (node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name),
        None,
    )
    assert function is not None, f"{name} must exist"
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace[name]


def load_ob_connection_method(name, namespace):
    source_path = REPO_ROOT / "rag" / "utils" / "ob_conn.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    ob_connection = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "OBConnection"
    )
    method = next(node for node in ob_connection.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace[name]


def test_set_progress_stops_a_canceled_task_when_task_record_is_missing():
    class TaskService:
        @staticmethod
        def update_progress(_task_id, _info):
            raise DoesNotExist()

    close_calls = []
    set_progress = load_function(
        "set_progress",
        {
            "DoesNotExist": DoesNotExist,
            "TaskCanceledException": TaskCanceledException,
            "TaskService": TaskService,
            "has_canceled": lambda _task_id: True,
            "close_connection": lambda: close_calls.append(True),
            "datetime": datetime,
            "logging": logging,
        },
    )

    with pytest.raises(TaskCanceledException):
        set_progress("task-1", prog=0.5, msg="Embedding chunks")

    assert close_calls == [True]


def test_cleanup_task_chunks_deletes_only_the_canceled_task_chunks():
    calls = []

    class DocStore:
        @staticmethod
        def index_exist(index_name, dataset_id):
            calls.append(("index_exist", index_name, dataset_id))
            return True

        @staticmethod
        def delete(condition, index_name, dataset_id):
            calls.append(("delete", condition, index_name, dataset_id))
            return 3

    cleanup_task_chunks = load_function(
        "cleanup_task_chunks",
        {
            "asyncio": asyncio,
            "settings": types.SimpleNamespace(docStoreConn=DocStore()),
            "search": types.SimpleNamespace(index_name=lambda tenant_id: f"idx_{tenant_id}"),
            "logging": logging,
        },
    )

    deleted = asyncio.run(cleanup_task_chunks("task-1", "tenant-1", "kb-1"))

    assert deleted == 3
    assert calls == [
        ("index_exist", "idx_tenant-1", "kb-1"),
        ("delete", {"task_id": "task-1"}, "idx_tenant-1", "kb-1"),
    ]


def test_cancel_all_task_of_keeps_cancel_marker_until_worker_must_stop():
    calls = []

    class TaskService:
        @staticmethod
        def query(doc_id):
            assert doc_id == "doc-1"
            return [types.SimpleNamespace(id="task-1"), types.SimpleNamespace(id="task-2")]

    class Redis:
        @staticmethod
        def set(key, value, exp):
            calls.append((key, value, exp))

    cancel_all_task_of = load_task_service_function(
        "cancel_all_task_of",
        {
            "TaskService": TaskService,
            "REDIS_CONN": Redis(),
            "TASK_CANCELLATION_TTL_SECONDS": 14_400,
            "logging": logging,
        },
    )

    cancel_all_task_of("doc-1")

    assert calls == [
        ("task-1-cancel", "x", 14_400),
        ("task-2-cancel", "x", 14_400),
    ]


def test_clear_canceled_removes_the_worker_cancel_marker():
    calls = []

    class Redis:
        @staticmethod
        def delete(key):
            calls.append(key)

    clear_canceled = load_task_service_function(
        "clear_canceled",
        {"REDIS_CONN": Redis(), "logging": logging},
    )

    clear_canceled("task-1")

    assert calls == ["task-1-cancel"]


def test_handle_task_acknowledges_cancellation_without_marking_the_task_failed():
    acknowledgements = []
    cleared = []

    class RedisMessage:
        def ack(self):
            acknowledgements.append(True)

    async def collect():
        return RedisMessage(), {"id": "task-1", "doc_id": "doc-1", "task_type": "naive"}

    async def do_handle_task(_task):
        raise TaskCanceledException("Task has been canceled")

    class PipelineOperationLogService:
        @staticmethod
        def record_pipeline_operation(**_kwargs):
            return None

    namespace = {
        "collect": collect,
        "do_handle_task": do_handle_task,
        "TaskCanceledException": TaskCanceledException,
        "TaskService": object,
        "PipelineOperationLogService": PipelineOperationLogService,
        "PipelineTaskType": types.SimpleNamespace(PARSE="parse"),
        "TASK_TYPE_TO_PIPELINE_TASK_TYPE": {},
        "CURRENT_TASKS": {},
        "DONE_TASKS": 0,
        "FAILED_TASKS": 0,
        "clear_canceled": lambda task_id: cleared.append(task_id),
        "has_canceled": lambda _task_id: True,
        "json": __import__("json"),
        "copy": copy,
        "logging": logging,
        "asyncio": asyncio,
        "exceptiongroup": types.SimpleNamespace(ExceptionGroup=ExceptionGroup),
        "set_progress": lambda *_args, **_kwargs: None,
    }
    handle_task = load_function("handle_task", namespace)

    asyncio.run(handle_task())

    assert namespace["DONE_TASKS"] == 0
    assert namespace["FAILED_TASKS"] == 0
    assert namespace["CURRENT_TASKS"] == {}
    assert acknowledgements == [True]
    assert cleared == ["task-1"]


def test_collect_acknowledges_a_queued_canceled_task_without_marking_it_failed():
    acknowledgements = []
    cleared = []

    class RedisMessage:
        def get_message(self):
            return {"id": "task-1", "task_type": "naive"}

        def ack(self):
            acknowledgements.append(True)

    class Redis:
        @staticmethod
        def queue_consumer(*_args):
            return RedisMessage()

    class TaskService:
        @staticmethod
        def get_task(task_id):
            assert task_id == "task-1"
            return {"id": task_id}

    namespace = {
        "settings": types.SimpleNamespace(get_svr_queue_names=lambda: ["queue"]),
        "REDIS_CONN": Redis(),
        "TaskService": TaskService,
        "SVR_CONSUMER_GROUP_NAME": "group",
        "CONSUMER_NAME": "consumer",
        "UNACKED_ITERATOR": iter(()),
        "DONE_TASKS": 0,
        "FAILED_TASKS": 0,
        "GRAPH_RAPTOR_FAKE_DOC_ID": "graph_raptor_x",
        "CANVAS_DEBUG_DOC_ID": "dataflow_x",
        "PIPELINE_SPECIAL_PROGRESS_FREEZE_TASK_TYPES": set(),
        "PipelineTaskType": types.SimpleNamespace(MEMORY="memory"),
        "has_canceled": lambda _task_id: True,
        "clear_canceled": lambda task_id: cleared.append(task_id),
        "logging": logging,
    }
    collect = load_function("collect", namespace)

    redis_msg, task = asyncio.run(collect())

    assert (redis_msg, task) == (None, None)
    assert namespace["FAILED_TASKS"] == 0
    assert acknowledgements == [True]
    assert cleared == ["task-1"]


def test_task_ownership_field_is_supported_by_fixed_schema_doc_stores():
    infinity_mapping = json.loads((REPO_ROOT / "conf" / "infinity_mapping.json").read_text(encoding="utf-8"))
    oceanbase_source = (REPO_ROOT / "rag" / "utils" / "ob_conn.py").read_text(encoding="utf-8")

    assert infinity_mapping["task_id"] == {"type": "varchar", "default": ""}
    assert 'Column("task_id", String(256), nullable=True, index=True' in oceanbase_source
    assert "column_task_id" in oceanbase_source


def test_oceanbase_migrates_task_id_before_creating_its_index():
    events = []

    class Client:
        metadata_obj = types.SimpleNamespace(refresh=lambda _tables: events.append("refresh"))

        @staticmethod
        def check_table_exists(_index_name):
            return False

        @staticmethod
        def refresh_metadata(_tables):
            events.append("refresh")

    class ExistingTable:
        client = Client()
        fulltext_search_columns = []

        @staticmethod
        def _create_table(_index_name):
            events.append("table")

        @staticmethod
        def _column_exist(_index_name, _column_name):
            return False

        @staticmethod
        def _index_exists(_index_name, _index_name_template):
            return False

        @staticmethod
        def _add_column(_index_name, column):
            events.append(f"column:{column.name}")

        @staticmethod
        def _add_index(_index_name, column_name):
            events.append(f"index:{column_name}")

        @staticmethod
        def _add_fulltext_index(_index_name, _column_name):
            raise AssertionError("no fulltext index should be created")

        @staticmethod
        def _add_vector_column(_index_name, _vector_size):
            events.append("vector-column")

        @staticmethod
        def _add_vector_index(_index_name, _vector_field_name):
            events.append("vector-index")

    def try_with_lock(lock_name, check_func, process_func):
        events.append(f"lock:{lock_name}")
        assert check_func() is False
        process_func()

    create_idx = load_ob_connection_method(
        "create_idx",
        {
            "_try_with_lock": try_with_lock,
            "column_order_id": types.SimpleNamespace(name="_order_id"),
            "column_group_id": types.SimpleNamespace(name="group_id"),
            "column_task_id": types.SimpleNamespace(name="task_id"),
            "index_columns": ["task_id"],
            "index_name_template": "%s_%s_idx",
            "fulltext_index_name_template": "%s_fts_idx",
        },
    )

    create_idx(ExistingTable(), "idx", "kb", 1024)

    assert events.index("column:task_id") < events.index("index:task_id")


def test_cancel_endpoints_reset_document_and_knowledgebase_chunk_statistics():
    document_app_source = (REPO_ROOT / "api" / "apps" / "document_app.py").read_text(encoding="utf-8")
    cancel_start = document_app_source.index('if str(req["run"]) == TaskStatus.CANCEL.value:')
    cancel_end = document_app_source.index('if all([("delete" not in req or req["delete"])', cancel_start)
    cancel_block = document_app_source[cancel_start:cancel_end]

    assert "DocumentService.clear_chunk_num_when_rerun(id)" in cancel_block
    assert 'info["chunk_num"] = 0' in cancel_block
    assert 'info["token_num"] = 0' in cancel_block

    sdk_source = (REPO_ROOT / "api" / "apps" / "sdk" / "doc.py").read_text(encoding="utf-8")
    sdk_module = ast.parse(sdk_source)
    stop_parsing = next(node for node in sdk_module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "stop_parsing")
    stop_parsing_source = ast.get_source_segment(sdk_source, stop_parsing)

    assert "DocumentService.clear_chunk_num_when_rerun(id)" in stop_parsing_source
    assert '"token_num": 0' in stop_parsing_source


def test_task_executor_checks_cancellation_immediately_before_incrementing_statistics():
    task_executor_source = (REPO_ROOT / "rag" / "svr" / "task_executor.py").read_text(encoding="utf-8")
    module = ast.parse(task_executor_source)
    do_handle_task = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "do_handle_task")
    source = ast.get_source_segment(task_executor_source, do_handle_task)
    first_increment = source.index("DocumentService.increment_chunk_num")
    last_cancel_check = source.rfind("if has_canceled(task_id):", 0, first_increment)

    assert last_cancel_check >= 0
    assert first_increment - last_cancel_check < 200


def test_task_executor_cleans_task_scoped_chunks_when_progress_stops_a_stale_task():
    module = ast.parse((REPO_ROOT / "rag" / "svr" / "task_executor.py").read_text(encoding="utf-8"))
    do_handle_task = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "do_handle_task")
    source = ast.get_source_segment((REPO_ROOT / "rag" / "svr" / "task_executor.py").read_text(encoding="utf-8"), do_handle_task)

    assert "except TaskCanceledException:" in source
    assert "if needs_cleanup or has_canceled(task_id):" in source


def test_insert_es_tags_each_chunk_with_its_creating_task():
    inserted = []

    class DocStore:
        @staticmethod
        def insert(documents, _index_name, _dataset_id):
            inserted.extend(documents)
            return []

    class TaskService:
        @staticmethod
        def update_chunk_ids(_task_id, _chunk_ids):
            return None

    insert_es = load_function(
        "insert_es",
        {
            "asyncio": asyncio,
            "settings": types.SimpleNamespace(docStoreConn=DocStore(), DOC_BULK_SIZE=4),
            "TaskService": TaskService,
            "has_canceled": lambda _task_id: False,
            "search": types.SimpleNamespace(index_name=lambda tenant_id: f"idx_{tenant_id}"),
            "DoesNotExist": DoesNotExist,
            "cleanup_task_chunks": None,
            "delete_image": None,
            "copy": copy,
            "xxhash": None,
        },
    )
    chunks = [{"id": "chunk-1", "doc_id": "doc-1", "content_with_weight": "content"}]

    assert asyncio.run(insert_es("task-1", "tenant-1", "kb-1", chunks, lambda **_kwargs: None)) is True

    assert chunks[0]["task_id"] == "task-1"
    assert inserted == chunks
