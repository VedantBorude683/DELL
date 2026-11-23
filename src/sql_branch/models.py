"""Data models and exceptions for Phase 3 SQL Branch."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SQLValidationError(ValueError):
    """Raised when generated SQL violates single-SELECT, allow-list, or safety rules."""


class SQLExecutionError(RuntimeError):
    """Raised when SQL execution fails or exceeds retries/timeouts."""


@dataclass(frozen=True)
class ValidatedSQL:
    sql: str
    tables: tuple[str, ...]
    limit_applied: int
    validator_backend: str


@dataclass(frozen=True)
class TabularResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str
    tables: list[str]
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "sql": self.sql,
            "tables": self.tables,
            "provenance": self.provenance,
        }
