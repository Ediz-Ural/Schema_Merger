"""Data contracts emitted by the deterministic profiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


ColumnType = Literal["string", "integer", "decimal", "date", "boolean"]
MappingStatus = Literal["auto", "review", "unmatched"]
ClusterStatus = Literal["auto", "review", "rejected"]


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


@dataclass(frozen=True)
class ClusterMember:
    """One spelling that belongs to an entity cluster.

    ``value`` is the merged-table value exactly as it appears, ``normalized`` is
    the comparison key it produced, and ``row_count`` is how many merged rows
    carry that spelling.
    """

    value: str
    normalized: str = ""
    row_count: int = 0


@dataclass(frozen=True)
class ClusterCandidate:
    """A spelling that *may* belong to a cluster but was not decided by code.

    Candidates are proposals only: they are never merged until a human moves
    them into ``members`` and approves the cluster.
    """

    value: str
    similarity: float
    suggestion: str
    source: str
    confidence: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class EntityClusterPlan:
    """One reviewable entity cluster as written to ``clusters.yaml``.

    ``status`` follows the mapping convention: ``auto`` is applied by ``apply``,
    ``review`` waits for a human and is reported as uncertain, and ``rejected``
    records a decision that the members are different products.
    """

    cluster_id: str
    target_column: str
    canonical: str
    status: ClusterStatus
    members: list[ClusterMember]
    candidates: list[ClusterCandidate] = field(default_factory=list)
    reason: str | None = None
