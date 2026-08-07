import ast
import logging
from pathlib import Path


DB_MODELS_PATH = Path(__file__).resolve().parents[4] / "api" / "db" / "db_models.py"


def load_close_connection(db):
    module = ast.parse(DB_MODELS_PATH.read_text(encoding="utf-8"), filename=str(DB_MODELS_PATH))
    function = next(
        node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "close_connection"
    )
    namespace = {"DB": db, "logging": logging}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(DB_MODELS_PATH), "exec"), namespace)
    return namespace["close_connection"]


class FakeDatabase:
    def __init__(self, closed):
        self.closed = closed
        self.close_calls = 0
        self.close_stale_calls = 0

    def is_closed(self):
        return self.closed

    def close(self):
        self.close_calls += 1

    def close_stale(self, age):
        self.close_stale_calls += 1


def test_close_connection_closes_only_the_current_open_connection():
    database = FakeDatabase(closed=False)
    close_connection = load_close_connection(database)

    close_connection()

    assert database.close_calls == 1
    assert database.close_stale_calls == 0


def test_close_connection_does_nothing_when_current_connection_is_closed():
    database = FakeDatabase(closed=True)
    close_connection = load_close_connection(database)

    close_connection()

    assert database.close_calls == 0
    assert database.close_stale_calls == 0
