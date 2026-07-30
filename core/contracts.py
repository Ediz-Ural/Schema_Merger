"""Validated, round-trippable YAML contracts for schema and mapping plans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from core.types import ColumnType, MappingEntry, MappingStatus, SourceMatch, TargetColumn


VALID_COLUMN_TYPES = frozenset({"string", "integer", "decimal", "date", "boolean"})
VALID_OUTPUT_FORMATS = frozenset({"xlsx", "csv", "sql"})
VALID_MAPPING_STATUSES = frozenset({"auto", "review", "unmatched"})


class ContractValidationError(ValueError):
    """Raised when a schema.yaml or mapping.yaml document is malformed."""


@dataclass(frozen=True)
class OutputSettings:
    format: str
    add_provenance: bool


@dataclass(frozen=True)
class SchemaContract:
    target_columns: list[TargetColumn]
    output: OutputSettings


@dataclass(frozen=True)
class MappingContract:
    entries: list[MappingEntry]


def load_schema(path: str | Path) -> SchemaContract:
    """Load and validate a target ``schema.yaml`` document."""

    document = _load_yaml(path, "schema.yaml")
    _expect_mapping(document, "schema.yaml kökü")
    _expect_keys(document, {"target_columns", "output"}, "schema.yaml")
    columns_data = document["target_columns"]
    if not isinstance(columns_data, list) or not columns_data:
        raise ContractValidationError("schema.yaml: target_columns boş olmayan bir liste olmalı.")
    columns = [_parse_target_column(item, index) for index, item in enumerate(columns_data)]
    names = [column.name for column in columns]
    if len(set(names)) != len(names):
        raise ContractValidationError("schema.yaml: target_columns isimleri benzersiz olmalı.")
    return SchemaContract(target_columns=columns, output=_parse_output(document["output"]))


def dump_schema(schema: SchemaContract, path: str | Path) -> None:
    """Validate then write a target schema in the documented YAML shape."""

    _validate_schema_contract(schema)
    _dump_yaml(
        {
            "target_columns": [
                {"name": column.name, "type": column.type, "required": column.required}
                for column in schema.target_columns
            ],
            "output": {
                "format": schema.output.format,
                "add_provenance": schema.output.add_provenance,
            },
        },
        path,
    )


def load_mapping(path: str | Path) -> MappingContract:
    """Load and validate a Phase 1 ``mapping.yaml`` plan."""

    document = _load_yaml(path, "mapping.yaml")
    if not isinstance(document, list):
        raise ContractValidationError("mapping.yaml kökü bir liste olmalı.")
    entries = [_parse_mapping_entry(item, index) for index, item in enumerate(document)]
    names = [entry.target_column for entry in entries]
    if len(set(names)) != len(names):
        raise ContractValidationError("mapping.yaml: target_column değerleri benzersiz olmalı.")
    return MappingContract(entries=entries)


def dump_mapping(mapping: MappingContract | Iterable[MappingEntry], path: str | Path) -> None:
    """Validate then write a mapping plan without dropping documented fields."""

    entries = mapping.entries if isinstance(mapping, MappingContract) else list(mapping)
    normalized = MappingContract(entries=entries)
    _validate_mapping_contract(normalized)
    _dump_yaml(
        [
            {
                "target_column": entry.target_column,
                "sources": [_source_to_dict(source) for source in entry.sources],
            }
            for entry in normalized.entries
        ],
        path,
    )


def _load_yaml(path: str | Path, label: str) -> Any:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file)
    except FileNotFoundError as error:
        raise ContractValidationError(f"{label} bulunamadı: {source}") from error
    except yaml.YAMLError as error:
        raise ContractValidationError(f"{label} geçerli YAML değil: {error}") from error


def _dump_yaml(document: Any, path: str | Path) -> None:
    destination = Path(path)
    with destination.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump(document, file, allow_unicode=True, sort_keys=False)


def _expect_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{context} bir nesne olmalı.")
    return value


def _expect_keys(value: Mapping[str, Any], keys: set[str], context: str) -> None:
    missing = keys.difference(value)
    if missing:
        raise ContractValidationError(f"{context}: zorunlu alan eksik: {', '.join(sorted(missing))}.")


def _parse_target_column(value: Any, index: int) -> TargetColumn:
    item = _expect_mapping(value, f"schema.yaml target_columns[{index}]")
    _expect_keys(item, {"name", "type", "required"}, f"schema.yaml target_columns[{index}]")
    name = _required_string(item["name"], f"target_columns[{index}].name")
    column_type = item["type"]
    if column_type not in VALID_COLUMN_TYPES:
        raise ContractValidationError(f"target_columns[{index}].type geçersiz: {column_type!r}.")
    if not isinstance(item["required"], bool):
        raise ContractValidationError(f"target_columns[{index}].required boolean olmalı.")
    return TargetColumn(name=name, type=column_type, required=item["required"])


def _parse_output(value: Any) -> OutputSettings:
    item = _expect_mapping(value, "schema.yaml output")
    _expect_keys(item, {"format", "add_provenance"}, "schema.yaml output")
    output_format = item["format"]
    if output_format not in VALID_OUTPUT_FORMATS:
        raise ContractValidationError(f"output.format geçersiz: {output_format!r}. xlsx, csv veya sql olmalı.")
    if not isinstance(item["add_provenance"], bool):
        raise ContractValidationError("output.add_provenance boolean olmalı.")
    return OutputSettings(format=output_format, add_provenance=item["add_provenance"])


def _parse_mapping_entry(value: Any, index: int) -> MappingEntry:
    item = _expect_mapping(value, f"mapping.yaml[{index}]")
    _expect_keys(item, {"target_column", "sources"}, f"mapping.yaml[{index}]")
    target_column = _required_string(item["target_column"], f"mapping[{index}].target_column")
    sources_data = item["sources"]
    if not isinstance(sources_data, list):
        raise ContractValidationError(f"mapping[{index}].sources bir liste olmalı.")
    return MappingEntry(
        target_column=target_column,
        sources=[_parse_source(source, index, source_index) for source_index, source in enumerate(sources_data)],
    )


def _parse_source(value: Any, entry_index: int, source_index: int) -> SourceMatch:
    context = f"mapping[{entry_index}].sources[{source_index}]"
    item = _expect_mapping(value, context)
    _expect_keys(item, {"file", "column", "confidence", "status"}, context)
    file = _required_string(item["file"], f"{context}.file")
    column = item["column"]
    if column is not None and not isinstance(column, str):
        raise ContractValidationError(f"{context}.column metin veya null olmalı.")
    confidence = item["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ContractValidationError(f"{context}.confidence sayı olmalı.")
    if not 0.0 <= float(confidence) <= 1.0:
        raise ContractValidationError(f"{context}.confidence 0 ile 1 arasında olmalı.")
    status = item["status"]
    if status not in VALID_MAPPING_STATUSES:
        raise ContractValidationError(
            f"{context}.status geçersiz: {status!r}. auto, review veya unmatched olmalı."
        )
    reason = item.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ContractValidationError(f"{context}.reason metin olmalı.")
    samples = item.get("samples")
    if samples is not None and not isinstance(samples, list):
        raise ContractValidationError(f"{context}.samples liste olmalı.")
    return SourceMatch(
        file=file,
        column=column,
        confidence=float(confidence),
        status=status,
        reason=reason,
        samples=samples,
    )


def _source_to_dict(source: SourceMatch) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": source.file,
        "column": source.column,
        "confidence": source.confidence,
        "status": source.status,
    }
    if source.reason is not None:
        result["reason"] = source.reason
    if source.samples is not None:
        result["samples"] = source.samples
    return result


def _required_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{context} boş olmayan metin olmalı.")
    return value


def _validate_schema_contract(schema: SchemaContract) -> None:
    _parse_output({"format": schema.output.format, "add_provenance": schema.output.add_provenance})
    if not schema.target_columns:
        raise ContractValidationError("schema.yaml: target_columns boş olmayan bir liste olmalı.")
    for index, column in enumerate(schema.target_columns):
        _parse_target_column(
            {"name": column.name, "type": column.type, "required": column.required}, index
        )


def _validate_mapping_contract(mapping: MappingContract) -> None:
    _parse_mapping_entries(mapping.entries)


def _parse_mapping_entries(entries: list[MappingEntry]) -> None:
    names = [entry.target_column for entry in entries]
    if len(set(names)) != len(names):
        raise ContractValidationError("mapping.yaml: target_column değerleri benzersiz olmalı.")
    for index, entry in enumerate(entries):
        _parse_mapping_entry(
            {
                "target_column": entry.target_column,
                "sources": [_source_to_dict(source) for source in entry.sources],
            },
            index,
        )
