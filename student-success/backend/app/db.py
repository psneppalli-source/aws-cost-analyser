"""Table singleton and small shared helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from .settings import settings
from .store import DynamoTable, SqliteTable

_table = None


def table():
    global _table
    if _table is None:
        s = settings()
        if s.storage == "dynamodb":
            _table = DynamoTable(s.table_name, s.region, s.dynamodb_endpoint)
        else:
            Path(s.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            _table = SqliteTable(s.sqlite_path)
    return _table


def set_table(t) -> None:
    global _table
    _table = t


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:12]
