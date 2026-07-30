"""Data contracts emitted by the deterministic profiler."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ColumnType = Literal["string", "integer", "decimal", "date", "boolean"]
MappingStatus = Literal["auto", "review", "unmatched"]


@dataclass(frozen=True)
class ColumnProfile:
    """Metadata and summary statistics for one source column.

    ``name`` is always the original column name. The profiler reports values and
    never alters source rows.
    """

    name: str
    inferred_type: ColumnType
    samples: list[object]
    unique_count: int
    null_ratio: float
    minimum: object | None = None
    maximum: object | None = None
    format_pattern: str | None = None


@dataclass(frozen=True)
class TableProfile:
    """Profile for one CSV table or one Excel worksheet."""

    name: str
    row_count: int
    columns: list[ColumnProfile]


@dataclass(frozen=True)
class FileProfile:
    """Profiles produced from a supported input file."""

    path: Path
    tables: list[TableProfile]


@dataclass(frozen=True)
class TargetColumn:
    """One column required by the user-defined target schema."""

    name: str
    type: ColumnType
    required: bool


@dataclass(frozen=True)
class SourceMatch:
    """A proposed source column for one target column."""

    file: str
    column: str | None
    confidence: float
    status: MappingStatus
    reason: str | None = None
    samples: list[object] | None = None


@dataclass(frozen=True)
class MappingEntry:
    """All source proposals made for a target column."""

    target_column: str
    sources: list[SourceMatch]
