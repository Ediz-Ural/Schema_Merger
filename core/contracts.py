"""Validated, round-trippable YAML contracts for schema and mapping plans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from core.types import (
    ClusterCandidate,
    ClusterMember,
    ColumnType,
    EntityClusterPlan,
    MappingEntry,
    MappingStatus,
    SourceMatch,
    TargetColumn,
)


VALID_COLUMN_TYPES = frozenset({"string", "integer", "decimal", "date", "boolean"})
VALID_OUTPUT_FORMATS = frozenset({"xlsx", "csv", "sql"})
VALID_MAPPING_STATUSES = frozenset({"auto", "review", "unmatched"})
VALID_CLUSTER_STATUSES = frozenset({"auto", "review", "rejected"})
VALID_CLUSTER_SUGGESTIONS = frozenset({"same", "different", "undecided"})

#: Written at the top of ``clusters.yaml`` so the approval rules travel with the
#: file the user edits.  YAML comments are ignored on load, so this round-trips.
CLUSTERS_HEADER = """# Schema Merger — entity kümeleri (kullanıcı onayı gerekir)
#
# status: auto      -> küme onaylı; apply üyeleri canonical değere getirir ve
#                      birebir aynı satırları tekilleştirir.
# status: review    -> küme onaysız; hiçbir üye birleştirilmez, merge_report'ta
#                      "belirsiz" olarak listelenir.
# status: rejected  -> üyeler farklı ürün; birleştirilmez, belirsiz sayılmaz.
#
# Onaylamak için: status'u auto yap. Bölmek için: üyeyi listeden çıkar (istersen
# yeni bir cluster_id ile ayrı küme yaz). candidates altındaki bir değeri kabul
# etmek için onu members'a taşı; bir değer yalnızca tek bir kümenin üyesi olabilir.
# canonical, members içindeki değerlerden biri olmalı.
"""


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


@dataclass(frozen=True)
class ClusterContract:
    """Every entity cluster proposed for one target column."""

    clusters: list[EntityClusterPlan]

    @property
    def target_column(self) -> str | None:
        """The single column these clusters describe, ``None`` when empty."""

        return self.clusters[0].target_column if self.clusters else None

    @property
    def approved(self) -> list[EntityClusterPlan]:
        """Clusters the user approved; only these are merged by ``apply``."""

        return [cluster for cluster in self.clusters if cluster.status == "auto"]

    @property
    def pending(self) -> list[EntityClusterPlan]:
        """Clusters still waiting for a decision — reported as uncertain."""

        return [cluster for cluster in self.clusters if cluster.status == "review"]


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


def load_clusters(path: str | Path) -> ClusterContract:
    """Load and validate a reviewable ``clusters.yaml`` document.

    The file is edited by hand between ``cluster`` and ``apply``, so every
    invariant a merge depends on is checked here: statuses are known, a value
    belongs to at most one cluster, and ``canonical`` is one of the members.
    """

    document = _load_yaml(path, "clusters.yaml")
    if document is None:
        return ClusterContract(clusters=[])
    if not isinstance(document, list):
        raise ContractValidationError("clusters.yaml kökü bir liste olmalı.")
    clusters = [_parse_cluster(item, index) for index, item in enumerate(document)]
    _validate_cluster_document(clusters)
    return ClusterContract(clusters=clusters)


def dump_clusters(
    clusters: ClusterContract | Iterable[EntityClusterPlan], path: str | Path
) -> None:
    """Validate then write clusters with the approval rules in the header."""

    items = clusters.clusters if isinstance(clusters, ClusterContract) else list(clusters)
    _validate_cluster_document(items)
    _dump_yaml(
        [_cluster_to_dict(cluster) for cluster in items],
        path,
        header=CLUSTERS_HEADER,
    )


def canonical_map(
    clusters: ClusterContract | Iterable[EntityClusterPlan],
) -> dict[str, tuple[str, str]]:
    """``value -> (canonical, cluster_id)`` for approved clusters only.

    This is the whole instruction set ``apply`` needs from entity resolution:
    reading it requires no embeddings and no LLM.  Clusters left in ``review``
    (or marked ``rejected``) are skipped, which is what keeps an unapproved
    cluster out of the merge.
    """

    plans = clusters.clusters if isinstance(clusters, ClusterContract) else clusters
    mapping: dict[str, tuple[str, str]] = {}
    for plan in plans:
        if plan.status != "auto":
            continue
        for member in plan.members:
            mapping[member.value] = (plan.canonical, plan.cluster_id)
    return mapping


def pending_reviews(mapping: MappingContract) -> list[tuple[str, SourceMatch]]:
    """Every ``(target_column, source)`` still waiting for a human decision.

    This is the review-guard predicate itself: the CLI and the web backend both
    read it, so ``apply`` refuses a blind merge on exactly the same rule
    (spec section 5/14).
    """

    return [
        (entry.target_column, source)
        for entry in mapping.entries
        for source in entry.sources
        if source.status == "review"
    ]


def pending_clusters(
    clusters: ClusterContract | Iterable[EntityClusterPlan],
) -> list[EntityClusterPlan]:
    """Approved-nothing clusters: the entity uncertainties a report must show."""

    plans = clusters.clusters if isinstance(clusters, ClusterContract) else clusters
    return [plan for plan in plans if plan.status == "review"]


def _validate_cluster_document(clusters: list[EntityClusterPlan]) -> None:
    """Re-validate whole-document rules that a single entry cannot enforce."""

    ids = [cluster.cluster_id for cluster in clusters]
    if len(set(ids)) != len(ids):
        raise ContractValidationError("clusters.yaml: cluster_id değerleri benzersiz olmalı.")
    columns = {cluster.target_column for cluster in clusters}
    if len(columns) > 1:
        raise ContractValidationError(
            "clusters.yaml tek bir hedef sütun için yazılır; birden çok target_column var: "
            + ", ".join(sorted(columns))
            + "."
        )
    seen: dict[str, str] = {}
    for index, cluster in enumerate(clusters):
        _parse_cluster(_cluster_to_dict(cluster), index)
        for member in cluster.members:
            owner = seen.get(member.value)
            if owner is not None:
                raise ContractValidationError(
                    f"clusters.yaml: '{member.value}' değeri hem '{owner}' hem "
                    f"'{cluster.cluster_id}' kümesinde üye. Bir değer tek kümeye ait olmalı."
                )
            seen[member.value] = cluster.cluster_id


def _parse_cluster(value: Any, index: int) -> EntityClusterPlan:
    context = f"clusters.yaml[{index}]"
    item = _expect_mapping(value, context)
    _expect_keys(item, {"cluster_id", "target_column", "canonical", "status", "members"}, context)
    cluster_id = _required_string(item["cluster_id"], f"{context}.cluster_id")
    target_column = _required_string(item["target_column"], f"{context}.target_column")
    canonical = _required_string(item["canonical"], f"{context}.canonical")
    status = item["status"]
    if status not in VALID_CLUSTER_STATUSES:
        raise ContractValidationError(
            f"{context}.status geçersiz: {status!r}. auto, review veya rejected olmalı."
        )
    members_data = item["members"]
    if not isinstance(members_data, list) or not members_data:
        raise ContractValidationError(f"{context}.members boş olmayan bir liste olmalı.")
    members = [_parse_cluster_member(member, context, position) for position, member in enumerate(members_data)]
    values = [member.value for member in members]
    if len(set(values)) != len(values):
        raise ContractValidationError(f"{context}.members içinde aynı değer birden çok kez var.")
    if canonical not in values:
        raise ContractValidationError(
            f"{context}.canonical ({canonical!r}) members içindeki değerlerden biri olmalı."
        )
    candidates_data = item.get("candidates") or []
    if not isinstance(candidates_data, list):
        raise ContractValidationError(f"{context}.candidates liste olmalı.")
    reason = item.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ContractValidationError(f"{context}.reason metin olmalı.")
    return EntityClusterPlan(
        cluster_id=cluster_id,
        target_column=target_column,
        canonical=canonical,
        status=status,
        members=members,
        candidates=[
            _parse_cluster_candidate(candidate, context, position)
            for position, candidate in enumerate(candidates_data)
        ],
        reason=reason,
    )


def _parse_cluster_member(value: Any, context: str, index: int) -> ClusterMember:
    position = f"{context}.members[{index}]"
    item = _expect_mapping(value, position)
    _expect_keys(item, {"value"}, position)
    member_value = _required_string(item["value"], f"{position}.value")
    normalized = item.get("normalized", "")
    if not isinstance(normalized, str):
        raise ContractValidationError(f"{position}.normalized metin olmalı.")
    row_count = item.get("row_count", 0)
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise ContractValidationError(f"{position}.row_count negatif olmayan bir tam sayı olmalı.")
    return ClusterMember(value=member_value, normalized=normalized, row_count=row_count)


def _parse_cluster_candidate(value: Any, context: str, index: int) -> ClusterCandidate:
    position = f"{context}.candidates[{index}]"
    item = _expect_mapping(value, position)
    _expect_keys(item, {"value", "similarity", "suggestion", "source"}, position)
    candidate_value = _required_string(item["value"], f"{position}.value")
    similarity = item["similarity"]
    if isinstance(similarity, bool) or not isinstance(similarity, (int, float)):
        raise ContractValidationError(f"{position}.similarity sayı olmalı.")
    if not 0.0 <= float(similarity) <= 1.0:
        raise ContractValidationError(f"{position}.similarity 0 ile 1 arasında olmalı.")
    suggestion = item["suggestion"]
    if suggestion not in VALID_CLUSTER_SUGGESTIONS:
        raise ContractValidationError(
            f"{position}.suggestion geçersiz: {suggestion!r}. "
            "same, different veya undecided olmalı."
        )
    source = _required_string(item["source"], f"{position}.source")
    confidence = item.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ContractValidationError(f"{position}.confidence sayı olmalı.")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ContractValidationError(f"{position}.confidence 0 ile 1 arasında olmalı.")
        confidence = float(confidence)
    reason = item.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ContractValidationError(f"{position}.reason metin olmalı.")
    return ClusterCandidate(
        value=candidate_value,
        similarity=float(similarity),
        suggestion=suggestion,
        source=source,
        confidence=confidence,
        reason=reason,
    )


def _cluster_to_dict(cluster: EntityClusterPlan) -> dict[str, Any]:
    result: dict[str, Any] = {
        "cluster_id": cluster.cluster_id,
        "target_column": cluster.target_column,
        "canonical": cluster.canonical,
        "status": cluster.status,
    }
    if cluster.reason is not None:
        result["reason"] = cluster.reason
    result["members"] = [
        {"value": member.value, "normalized": member.normalized, "row_count": member.row_count}
        for member in cluster.members
    ]
    if cluster.candidates:
        result["candidates"] = [
            _candidate_to_dict(candidate) for candidate in cluster.candidates
        ]
    return result


def _candidate_to_dict(candidate: ClusterCandidate) -> dict[str, Any]:
    result: dict[str, Any] = {
        "value": candidate.value,
        "similarity": round(candidate.similarity, 6),
        "suggestion": candidate.suggestion,
        "source": candidate.source,
    }
    if candidate.confidence is not None:
        result["confidence"] = round(candidate.confidence, 6)
    if candidate.reason is not None:
        result["reason"] = candidate.reason
    return result


def _load_yaml(path: str | Path, label: str) -> Any:
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file)
    except FileNotFoundError as error:
        raise ContractValidationError(f"{label} bulunamadı: {source}") from error
    except yaml.YAMLError as error:
        raise ContractValidationError(f"{label} geçerli YAML değil: {error}") from error


def _dump_yaml(document: Any, path: str | Path, *, header: str | None = None) -> None:
    destination = Path(path)
    with destination.open("w", encoding="utf-8", newline="\n") as file:
        if header:
            file.write(header if header.endswith("\n") else header + "\n")
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
