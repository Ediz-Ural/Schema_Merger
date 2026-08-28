"""Deterministic vertical transformation from a mapping plan to target rows.

This module intentionally has no dependency on :mod:`core.llm`, not even an
indirect one: entity resolution reaches it only as the approved ``clusters.yaml``
document, which is read with :func:`core.contracts.canonical_map`.  It reads each
source independently, converts values according to the target schema, and
concatenates rows only vertically.  CSV input is processed in chunks so callers
can tune memory use for large files.  :func:`deduplicate` then applies approved
entity clusters to the result.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pandas as pd
import polars as pl

from core.contracts import (
    ClusterContract,
    MappingContract,
    SchemaContract,
    canonical_map,
    load_mapping,
    load_schema,
)
from core.normalize import NormalizationError, TargetType, normalize_value
from core.types import EntityClusterPlan, MappingEntry, SourceMatch, TargetColumn


DEFAULT_CHUNK_SIZE = 50_000

#: Provenance column naming the approved cluster a merged row came from.
ENTITY_CLUSTER_COLUMN = "_entity_cluster_id"

#: Provenance column counting how many source rows a written row stands for.
MERGED_ROW_COUNT_COLUMN = "_merged_row_count"

#: Separator used when a deduplicated row carries several origin values.
PROVENANCE_SEPARATOR = "; "


class TransformError(ValueError):
    """Raised for invalid inputs or a mapping plan that cannot be applied."""


@dataclass(frozen=True)
class TransformationResult:
    """The transformed rows, their per-row provenance, and failure counters.

    ``dataframe`` contains target-schema columns only.  ``provenance`` has the
    same row order and contains ``source_file`` plus one source-column field per
    target column.  A ``None`` provenance column denotes an unmatched target.
    Invalid values are represented by null in ``dataframe`` and counted in
    ``conversion_error_counts``; no row is removed.
    """

    dataframe: pl.DataFrame
    provenance: pl.DataFrame
    conversion_error_counts: dict[str, int]

    @property
    def row_count(self) -> int:
        return self.dataframe.height

    @property
    def conversion_error_count(self) -> int:
        return sum(self.conversion_error_counts.values())


def transform(
    mapping: MappingContract | str | Path,
    source_files: Sequence[str | Path],
    target_schema: SchemaContract | str | Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> TransformationResult:
    """Apply an approved mapping to source files as a vertical union.

    ``source_files`` are explicit because ``mapping.yaml`` records portable file
    names rather than absolute paths.  Source matches are associated by file
    name, as emitted by the analyzer.  CSV files are read in ``chunk_size``
    records; Excel worksheets are yielded one at a time.
    """

    if chunk_size < 1:
        raise TransformError("chunk_size must be at least 1")
    plan = load_mapping(mapping) if isinstance(mapping, (str, Path)) else mapping
    schema = load_schema(target_schema) if isinstance(target_schema, (str, Path)) else target_schema
    paths = [Path(path) for path in source_files]
    if not paths:
        raise TransformError("At least one source file is required")
    _ensure_unique_file_names(paths)
    entries = _entries_for_schema(plan, schema)
    data_rows: list[dict[str, object | None]] = []
    provenance_rows: list[dict[str, str | None]] = []
    failures = {column.name: 0 for column in schema.target_columns}

    for path in paths:
        if not path.is_file():
            raise TransformError(f"Input file does not exist or is not a file: {path}")
        matches = _matches_for_file(entries, path)
        saw_columns: set[str] = set()
        for frame in _read_frames(path, chunk_size):
            saw_columns.update(str(column) for column in frame.columns)
            _append_frame_rows(
                frame,
                path.name,
                schema.target_columns,
                matches,
                data_rows,
                provenance_rows,
                failures,
            )
        _validate_source_columns(path, matches, saw_columns)

    return TransformationResult(
        dataframe=_target_dataframe(data_rows, schema.target_columns),
        provenance=_provenance_dataframe(provenance_rows, schema.target_columns),
        conversion_error_counts=failures,
    )


def transform_files(
    mapping: MappingContract | str | Path,
    source_files: Sequence[str | Path],
    target_schema: SchemaContract | str | Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> TransformationResult:
    """Named alias for :func:`transform` for application-layer callers."""

    return transform(mapping, source_files, target_schema, chunk_size=chunk_size)


def original_value_column(target_column: str) -> str:
    """Provenance column holding the pre-canonical value of ``target_column``."""

    return f"{target_column}_original_value"


@dataclass(frozen=True)
class DeduplicationResult:
    """The deduplicated transformation plus what entity resolution changed."""

    result: TransformationResult
    target_column: str
    merged_cluster_count: int
    canonicalized_row_count: int
    duplicate_row_count: int


def deduplicate(
    result: TransformationResult,
    clusters: ClusterContract | Sequence[EntityClusterPlan],
    *,
    column: str | None = None,
) -> DeduplicationResult:
    """Apply approved entity clusters to a transformed table.

    Two deterministic steps, both driven by ``clusters.yaml`` alone — no LLM and
    no similarity is recomputed here (spec §14).  First every member spelling of
    an **approved** (``status: auto``) cluster is rewritten to that cluster's
    canonical value.  Then rows that became identical across *all* target
    columns collapse — but only when they came from **different spellings**, so
    only the duplicates entity resolution itself created are removed.  Two rows
    that were already identical (the same product sold twice at the same price)
    stay two rows, and rows outside an approved cluster are never touched, so a
    cluster left in ``review`` cannot silently lose rows.

    Provenance survives the collapse: the surviving row keeps every origin value
    of the rows it absorbed (joined with ``"; "``), names its cluster in
    ``_entity_cluster_id``, keeps the original spellings in
    ``<column>_original_value``, and counts the rows it stands for in
    ``_merged_row_count``.
    """

    plans = list(clusters.clusters) if isinstance(clusters, ClusterContract) else list(clusters)
    target = column or next((plan.target_column for plan in plans), None)
    if not target:
        raise TransformError(
            "Entity tekilleştirme için hedef sütun gerekli: clusters.yaml boş, --column ver."
        )
    if target not in result.dataframe.columns:
        raise TransformError(f"Entity sütunu '{target}' birleşik veride yok.")
    if result.dataframe.schema[target] != pl.String:
        raise TransformError(
            f"Entity tekilleştirme yalnızca metin sütunlarında yapılır; '{target}' metin değil."
        )
    mismatched = {plan.target_column for plan in plans} - {target}
    if mismatched:
        raise TransformError(
            f"clusters.yaml '{', '.join(sorted(mismatched))}' sütununu tanımlıyor, "
            f"tekilleştirme ise '{target}' üzerinde isteniyor."
        )

    canonical = canonical_map(plans)
    columns = list(result.dataframe.columns)
    provenance_columns = list(result.provenance.columns)

    survivors: dict[tuple[object, ...], list[int]] = {}
    data_rows: list[dict[str, object | None]] = []
    provenance_rows: list[dict[str, object]] = []
    merged_clusters: set[str] = set()
    canonicalized = 0
    duplicates = 0

    for data_row, provenance_row in zip(
        result.dataframe.rows(named=True), result.provenance.rows(named=True)
    ):
        value = data_row[target]
        entry = canonical.get(value) if isinstance(value, str) else None
        if entry is None:
            data_rows.append(dict(data_row))
            provenance_rows.append(_entity_provenance(provenance_row, provenance_columns, None, None))
            continue

        canonical_value, cluster_id = entry
        merged_clusters.add(cluster_id)
        merged_row = dict(data_row)
        merged_row[target] = canonical_value
        if canonical_value != value:
            canonicalized += 1

        key = (cluster_id, *(merged_row[name] for name in columns))
        group = survivors.setdefault(key, [])
        position = _absorbing_row(group, provenance_rows, value)
        if position is None:
            group.append(len(data_rows))
            data_rows.append(merged_row)
            provenance_rows.append(
                _entity_provenance(provenance_row, provenance_columns, cluster_id, value)
            )
            continue
        _absorb_provenance(provenance_rows[position], provenance_row, provenance_columns, value)
        duplicates += 1

    deduplicated = TransformationResult(
        dataframe=_rebuild_dataframe(data_rows, result.dataframe),
        provenance=_entity_provenance_dataframe(provenance_rows, provenance_columns, target),
        conversion_error_counts=dict(result.conversion_error_counts),
    )
    return DeduplicationResult(
        result=deduplicated,
        target_column=target,
        merged_cluster_count=len(merged_clusters),
        canonicalized_row_count=canonicalized,
        duplicate_row_count=duplicates,
    )


def _absorbing_row(
    group: Sequence[int], provenance_rows: Sequence[dict[str, object]], value: str
) -> int | None:
    """The row this duplicate folds into, or ``None`` when it stands on its own.

    A row only folds into a row built from a *different* spelling.  Repeating
    the same spelling twice is real repetition in the source data, not something
    entity resolution unified, so both rows survive.
    """

    for position in group:
        if value not in provenance_rows[position]["_originals"]:  # type: ignore[operator]
            return position
    return None


def _entity_provenance(
    provenance_row: dict[str, object],
    columns: Sequence[str],
    cluster_id: str | None,
    original_value: str | None,
) -> dict[str, object]:
    """Start a provenance row; every origin field becomes an ordered value list."""

    row: dict[str, object] = {
        name: [provenance_row[name]] if provenance_row[name] is not None else []
        for name in columns
    }
    row[ENTITY_CLUSTER_COLUMN] = cluster_id
    row["_originals"] = [original_value] if original_value is not None else []
    row[MERGED_ROW_COUNT_COLUMN] = 1
    return row


def _absorb_provenance(
    survivor: dict[str, object],
    provenance_row: dict[str, object],
    columns: Sequence[str],
    original_value: str | None,
) -> None:
    """Fold a duplicate row's origins into the row that survives it."""

    for name in columns:
        value = provenance_row[name]
        if value is not None and value not in survivor[name]:
            survivor[name].append(value)  # type: ignore[union-attr]
    if original_value is not None and original_value not in survivor["_originals"]:
        survivor["_originals"].append(original_value)  # type: ignore[union-attr]
    survivor[MERGED_ROW_COUNT_COLUMN] = int(survivor[MERGED_ROW_COUNT_COLUMN]) + 1


def _rebuild_dataframe(rows: list[dict[str, object | None]], template: pl.DataFrame) -> pl.DataFrame:
    values = {name: [row.get(name) for row in rows] for name in template.columns}
    return pl.DataFrame(values).cast(dict(template.schema), strict=False)


def _entity_provenance_dataframe(
    rows: list[dict[str, object]], columns: Sequence[str], target_column: str
) -> pl.DataFrame:
    original_column = original_value_column(target_column)
    values: dict[str, list[object]] = {
        name: [_join_provenance(row[name]) for row in rows] for name in columns
    }
    values[ENTITY_CLUSTER_COLUMN] = [row[ENTITY_CLUSTER_COLUMN] for row in rows]
    values[original_column] = [_join_provenance(row["_originals"]) for row in rows]
    values[MERGED_ROW_COUNT_COLUMN] = [row[MERGED_ROW_COUNT_COLUMN] for row in rows]
    frame = pl.DataFrame(values)
    text_columns = [*columns, ENTITY_CLUSTER_COLUMN, original_column]
    return frame.cast(
        {
            **{name: pl.String for name in text_columns},
            MERGED_ROW_COUNT_COLUMN: pl.Int64,
        },
        strict=False,
    )


def _join_provenance(values: object) -> str | None:
    items = [str(value) for value in values] if isinstance(values, list) else []
    return PROVENANCE_SEPARATOR.join(items) if items else None


def _entries_for_schema(plan: MappingContract, schema: SchemaContract) -> dict[str, MappingEntry]:
    entries = {entry.target_column: entry for entry in plan.entries}
    expected = {column.name for column in schema.target_columns}
    missing = expected.difference(entries)
    extra = set(entries).difference(expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing targets: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unknown targets: {', '.join(sorted(extra))}")
        raise TransformError("Mapping and target schema disagree (" + "; ".join(details) + ")")
    return entries


def _ensure_unique_file_names(paths: Sequence[Path]) -> None:
    names = [path.name for path in paths]
    if len(names) != len(set(names)):
        raise TransformError("Source file names must be unique because mapping.yaml identifies files by name")


def _matches_for_file(entries: dict[str, MappingEntry], path: Path) -> dict[str, SourceMatch | None]:
    result: dict[str, SourceMatch | None] = {}
    for target, entry in entries.items():
        candidates = [match for match in entry.sources if _same_file(match.file, path)]
        if len(candidates) > 1:
            raise TransformError(f"Mapping has multiple sources for '{target}' in '{path.name}'")
        result[target] = candidates[0] if candidates else None
    return result


def _same_file(mapped_file: str, path: Path) -> bool:
    return mapped_file == str(path) or Path(mapped_file).name == path.name


def _read_frames(path: Path, chunk_size: int) -> Iterator[pd.DataFrame]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        yield from _read_csv_chunks(path, chunk_size)
        return
    if suffix != ".xlsx":
        raise TransformError(f"Unsupported input format '{path.suffix or '<none>'}'. Only .csv and .xlsx are supported.")
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=object, engine="openpyxl")
    except Exception as error:  # pandas/openpyxl report various exceptions
        raise TransformError(f"Could not read Excel file '{path}': {error}") from error
    yield from sheets.values()


def _read_csv_chunks(path: Path, chunk_size: int) -> Iterator[pd.DataFrame]:
    encoding, delimiter = _csv_settings(path)
    try:
        yield from pd.read_csv(
            path,
            dtype=object,
            encoding=encoding,
            sep=delimiter,
            chunksize=chunk_size,
            keep_default_na=False,
        )
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as error:
        raise TransformError(f"Could not read CSV file '{path}': {error}") from error


def _csv_settings(path: Path) -> tuple[str, str]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                preview = handle.read(4096)
            try:
                delimiter = csv.Sniffer().sniff(preview, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
            return encoding, delimiter
        except (OSError, UnicodeDecodeError) as error:
            last_error = error
    raise TransformError(f"Could not read CSV file '{path}': {last_error}") from last_error


def _append_frame_rows(
    frame: pd.DataFrame,
    source_file: str,
    columns: Sequence[TargetColumn],
    matches: dict[str, SourceMatch | None],
    data_rows: list[dict[str, object | None]],
    provenance_rows: list[dict[str, str | None]],
    failures: dict[str, int],
) -> None:
    for _, source_row in frame.iterrows():
        target_row: dict[str, object | None] = {}
        provenance_row: dict[str, str | None] = {"source_file": source_file}
        for target in columns:
            match = matches[target.name]
            source_column = match.column if match is not None else None
            provenance_row[target.name] = source_column
            if source_column is None or source_column not in frame.columns:
                target_row[target.name] = None
                continue
            raw_value = source_row[source_column]
            try:
                target_row[target.name] = normalize_value(raw_value, target.type)
            except NormalizationError:
                target_row[target.name] = None
                failures[target.name] += 1
        data_rows.append(target_row)
        provenance_rows.append(provenance_row)


def _validate_source_columns(
    path: Path, matches: dict[str, SourceMatch | None], saw_columns: Iterable[str]
) -> None:
    available = set(saw_columns)
    for target, match in matches.items():
        if match is not None and match.column is not None and match.column not in available:
            raise TransformError(
                f"Mapped source column '{match.column}' for target '{target}' was not found in '{path.name}'"
            )


def _target_dataframe(rows: list[dict[str, object | None]], columns: Sequence[TargetColumn]) -> pl.DataFrame:
    names = [column.name for column in columns]
    values = {name: [row.get(name) for row in rows] for name in names}
    frame = pl.DataFrame(values)
    dtypes = {
        "string": pl.String,
        "integer": pl.Int64,
        "decimal": pl.Float64,
        "date": pl.Date,
        "boolean": pl.Boolean,
    }
    return frame.cast({column.name: dtypes[column.type] for column in columns}, strict=False)


def _provenance_dataframe(rows: list[dict[str, str | None]], columns: Sequence[TargetColumn]) -> pl.DataFrame:
    names = ["source_file", *(column.name for column in columns)]
    values = {name: [row.get(name) for row in rows] for name in names}
    return pl.DataFrame(values).cast({name: pl.String for name in names}, strict=False)
