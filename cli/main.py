"""CLI entry point for profiling inputs, planning merges, and applying plans.

Phase 1 (``analyze``) is the only command that talks to an LLM.  Phase 2
(``apply``) is deterministic: it never imports or builds an LLM client, it
refuses to merge while any match is still in ``review``, and it always writes
provenance columns (spec §5/§14).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from core.contracts import (
    VALID_OUTPUT_FORMATS,
    ContractValidationError,
    MappingContract,
    dump_clusters,
    dump_mapping,
    load_clusters,
    load_mapping,
    load_schema,
)
from core.entity import (
    BLOCKING_STRATEGIES,
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_LOW_THRESHOLD,
    EntityError,
    SimilarityThresholds,
    grey_pairs,
    make_blocks,
    resolve_pairs,
    to_cluster_plans,
)
from core.entity import cluster as build_clusters
from core.llm import (
    EmbeddingClient,
    LLMClient,
    LLMConfigurationError,
    create_embedding_client,
    create_llm_client,
)
from core.matcher import match_profiles
from core.profiler import ProfileError, profile_file
from core.transformer import TransformError, deduplicate, transform
from core.types import SourceMatch
from core.writer import DEFAULT_REPORT_NAME, EntitySummary, WriteError, write


#: Exit code used when the review-guard stops a blind merge (spec §5).
REVIEW_GUARD_EXIT_CODE = 3

#: File name looked up next to mapping.yaml when ``--target-schema`` is omitted.
DEFAULT_SCHEMA_NAME = "schema.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="merger", description="Schema Merger commands")
    subcommands = parser.add_subparsers(dest="command", required=True)
    profile = subcommands.add_parser("profile", help="Profile a CSV or XLSX input file")
    profile.add_argument("--input", required=True, type=Path, help="Path to a .csv or .xlsx file")
    profile.add_argument("--sheet", help="Profile one named worksheet (XLSX only)")

    analyze = subcommands.add_parser("analyze", help="Create a mapping plan without merging data")
    analyze.add_argument(
        "--inputs",
        required=True,
        nargs="+",
        type=Path,
        help="One or more .csv or .xlsx source files",
    )
    analyze.add_argument("--target-schema", required=True, type=Path, help="Path to target schema.yaml")
    analyze.add_argument("--out", required=True, type=Path, help="Destination mapping.yaml path")

    cluster = subcommands.add_parser(
        "cluster",
        help="Propose entity clusters for one column of an approved plan (uses an LLM)",
    )
    cluster.add_argument("--mapping", required=True, type=Path, help="Path to the approved mapping.yaml")
    cluster.add_argument("--column", required=True, help="Target column to resolve entities for")
    cluster.add_argument("--out", required=True, type=Path, help="Destination clusters.yaml path")
    cluster.add_argument(
        "--target-schema",
        type=Path,
        help=f"Target schema.yaml; defaults to {DEFAULT_SCHEMA_NAME} next to the mapping",
    )
    cluster.add_argument(
        "--inputs",
        nargs="+",
        type=Path,
        help="Source files; defaults to the file names recorded in the mapping",
    )
    cluster.add_argument(
        "--strategy",
        nargs="+",
        choices=list(BLOCKING_STRATEGIES),
        default=["prefix"],
        help="Blocking strategy or composite key (default: prefix)",
    )
    cluster.add_argument(
        "--high",
        type=float,
        default=DEFAULT_HIGH_THRESHOLD,
        help=f"Similarity at or above which a pair merges without an LLM (default {DEFAULT_HIGH_THRESHOLD})",
    )
    cluster.add_argument(
        "--low",
        type=float,
        default=DEFAULT_LOW_THRESHOLD,
        help=f"Similarity below which a pair is a different product (default {DEFAULT_LOW_THRESHOLD})",
    )
    cluster.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip the grey-zone LLM step; grey pairs stay undecided for the user",
    )

    apply = subcommands.add_parser("apply", help="Apply an approved mapping plan without an LLM")
    apply.add_argument("--mapping", required=True, type=Path, help="Path to the approved mapping.yaml")
    apply.add_argument("--out", required=True, type=Path, help="Destination merged.<fmt> path")
    apply.add_argument(
        "--format",
        dest="output_format",
        choices=sorted(VALID_OUTPUT_FORMATS),
        help="Output format; defaults to output.format from the target schema",
    )
    apply.add_argument(
        "--target-schema",
        type=Path,
        help=f"Target schema.yaml; defaults to {DEFAULT_SCHEMA_NAME} next to the mapping",
    )
    apply.add_argument(
        "--inputs",
        nargs="+",
        type=Path,
        help="Source files; defaults to the file names recorded in the mapping",
    )
    apply.add_argument(
        "--report",
        type=Path,
        help=f"Report path; defaults to {DEFAULT_REPORT_NAME} next to --out",
    )
    apply.add_argument(
        "--clusters",
        type=Path,
        help="Approved clusters.yaml; only 'auto' clusters are deduplicated",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    llm_client: LLMClient | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> int:
    """Run a command.

    ``llm_client`` and ``embedding_client`` are injection points for tests.
    Normal CLI invocations construct the configured clients only for the
    ``analyze`` and ``cluster`` commands.
    """

    args = build_parser().parse_args(argv)
    if args.command == "profile":
        try:
            result = profile_file(args.input, sheet=args.sheet)
        except ProfileError as error:
            print(f"Error: {error}")
            return 2
        print(f"File: {result.path}")
        for table in result.tables:
            print(f"\nTable: {table.name} ({table.row_count} rows)")
            for column in table.columns:
                details = [
                    f"type={column.inferred_type}",
                    f"null_ratio={column.null_ratio:.2%}",
                    f"unique={column.unique_count}",
                    f"samples={column.samples!r}",
                ]
                if column.minimum is not None:
                    details.append(f"min={column.minimum!r}")
                    details.append(f"max={column.maximum!r}")
                if column.format_pattern:
                    details.append(f"pattern={column.format_pattern}")
                print(f"  - {column.name}: " + ", ".join(details))
        return 0
    if args.command == "analyze":
        return _analyze(args.inputs, args.target_schema, args.out, llm_client)
    if args.command == "cluster":
        return _cluster(args, llm_client, embedding_client)
    if args.command == "apply":
        # No LLM client is built here: Phase 2 is deterministic (spec §14).
        return _apply(
            args.mapping,
            args.out,
            args.output_format,
            args.target_schema,
            args.inputs,
            args.report,
            args.clusters,
        )
    return 1


def _analyze(
    inputs: list[Path], target_schema: Path, output: Path, llm_client: LLMClient | None
) -> int:
    """Profile sources and write a reviewable mapping plan; never merge rows."""

    try:
        schema = load_schema(target_schema)
        profiles = [profile_file(input_path) for input_path in inputs]
        client = llm_client or create_llm_client()
        mapping = match_profiles(profiles, schema, client)
        dump_mapping(mapping, output)
    except (ContractValidationError, ProfileError, LLMConfigurationError) as error:
        print(f"Error: {error}")
        return 2
    except OSError as error:
        print(f"Error: mapping plan could not be written to '{output}': {error}")
        return 2

    counts = {status: 0 for status in ("auto", "review", "unmatched")}
    for entry in mapping.entries:
        for source in entry.sources:
            counts[source.status] += 1

    _configure_utf8_stdout()
    print(f"\u2713 {counts['auto']} s\u00fctun otomatik e\u015fle\u015fti")
    print(f"\u26a0 {counts['review']} s\u00fctun onay bekliyor (review)")
    print(f"\u2717 {counts['unmatched']} s\u00fctun hi\u00e7bir dosyada bulunamad\u0131")
    print(f"\u2192 Plan\u0131 d\u00fczenle: {output}, sonra: merger apply")
    return 0


def _cluster(args, llm_client: LLMClient | None, embedding_client: EmbeddingClient | None) -> int:
    """Propose entity clusters for one target column of an approved plan.

    This is still Phase 1 work — embeddings and, for the grey band only, an LLM
    — so it writes a reviewable ``clusters.yaml`` and merges nothing.  Only the
    distinct values of the chosen column are compared; whole rows never reach a
    provider (spec §14).
    """

    _configure_utf8_stdout()
    try:
        mapping = load_mapping(args.mapping)
    except ContractValidationError as error:
        print(f"Error: {error}")
        return 2

    pending = _pending_reviews(mapping)
    if pending:
        _report_review_guard(pending, args.mapping, command="cluster")
        return REVIEW_GUARD_EXIT_CODE

    try:
        thresholds = SimilarityThresholds(high=args.high, low=args.low)
        schema = load_schema(_resolve_schema_path(args.target_schema, args.mapping))
        sources = args.inputs if args.inputs else _resolve_source_files(mapping, args.mapping)
        result = transform(mapping, sources, schema)
        column = next((item for item in schema.target_columns if item.name == args.column), None)
        if column is None:
            names = ", ".join(item.name for item in schema.target_columns)
            print(f"Error: '{args.column}' hedef şemada yok. Sütunlar: {names}")
            return 2
        if column.type != "string":
            # apply would refuse to deduplicate it later; say so before the run.
            print(f"Error: entity çözümü metin sütunlarında yapılır; '{args.column}' türü {column.type}.")
            return 2
        records = _value_records(result.dataframe[args.column].to_list())
        blocks = make_blocks(records, strategy=args.strategy)
        embedder = embedding_client or create_embedding_client()
        llm = None if args.no_llm else (llm_client or create_llm_client())
        decisions = resolve_pairs(blocks, embedder=embedder, llm=llm, thresholds=thresholds)
        clusters = build_clusters(decisions, target_column=args.column)
        plans = to_cluster_plans(clusters)
        dump_clusters(plans, args.out)
    except (ContractValidationError, EntityError, TransformError, LLMConfigurationError) as error:
        print(f"Error: {error}")
        return 2
    except OSError as error:
        print(f"Error: küme dosyası yazılamadı '{args.out}': {error}")
        return 2

    auto = len(clusters.auto_clusters)
    review = len(clusters.review_clusters)
    print(f"✓ {auto} küme yüksek güvenle birleşmeye hazır (status: auto)")
    print(f"⚠ {review} küme onay bekliyor (status: review)")
    print(f"• {len(records)} farklı değer, {len(decisions)} aday çift, {len(grey_pairs(decisions))} gri çift")
    print(f"→ Kümeleri düzenle: {args.out}, sonra: merger apply --clusters {args.out}")
    return 0


def _value_records(values: list[object]) -> list[dict[str, object]]:
    """Distinct non-empty values of a column with how many rows carry each.

    Entity resolution compares spellings, not rows, so the same value repeated a
    thousand times is embedded once.  The count rides along because the most
    frequent spelling becomes the cluster's canonical value.
    """

    counts: dict[str, int] = {}
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not text.strip():
            continue
        counts[text] = counts.get(text, 0) + 1
    return [{"name": text, "row_count": count} for text, count in counts.items()]


def _apply(
    mapping_path: Path,
    output: Path,
    output_format: str | None,
    target_schema: Path | None,
    inputs: list[Path] | None,
    report: Path | None,
    clusters_path: Path | None = None,
) -> int:
    """Apply an approved plan deterministically; stop while any match is review."""

    _configure_utf8_stdout()
    try:
        mapping = load_mapping(mapping_path)
    except ContractValidationError as error:
        print(f"Error: {error}")
        return 2

    pending = _pending_reviews(mapping)
    if pending:
        _report_review_guard(pending, mapping_path)
        return REVIEW_GUARD_EXIT_CODE

    entity: EntitySummary | None = None
    try:
        schema_path = _resolve_schema_path(target_schema, mapping_path)
        schema = load_schema(schema_path)
        sources = inputs if inputs else _resolve_source_files(mapping, mapping_path)
        result = transform(mapping, sources, schema)
        if clusters_path is not None:
            contract = load_clusters(clusters_path)
            if contract.clusters:
                dedup = deduplicate(result, contract)
                result = dedup.result
                entity = EntitySummary.from_deduplication(dedup, contract)
            else:
                # Nothing to decide on: report the empty run instead of failing.
                entity = EntitySummary(target_column="")
        written = write(
            result,
            mapping,
            schema,
            output,
            output_format=output_format,
            report_path=report,
            table_name=output.stem,
            add_provenance=schema.output.add_provenance,
            entity=entity,
        )
    except (ContractValidationError, TransformError, WriteError) as error:
        print(f"Error: {error}")
        return 2
    except OSError as error:
        print(f"Error: çıktı yazılamadı '{output}': {error}")
        return 2

    print(f"✓ {written.row_count} satır yazıldı: {written.merged_path}")
    print(
        f"• {written.null_cell_count} boş hücre (null), "
        f"{written.conversion_error_count} dönüştürme hatası"
    )
    if entity is not None:
        print(
            f"• entity: {entity.merged_cluster_count} onaylı küme uygulandı, "
            f"{entity.duplicate_row_count} yinelenen satır tekilleştirildi"
        )
        if entity.pending_clusters:
            print(
                f"⚠ {len(entity.pending_clusters)} küme onaysız kaldı; birleştirilmedi, "
                "raporda 'belirsiz' olarak listelendi"
            )
    print(f"→ Rapor: {written.report_path}")
    return 0


def _pending_reviews(mapping: MappingContract) -> list[tuple[str, SourceMatch]]:
    """Every ``(target_column, source)`` pair still waiting for a decision."""

    return [
        (entry.target_column, source)
        for entry in mapping.entries
        for source in entry.sources
        if source.status == "review"
    ]


def _report_review_guard(
    pending: list[tuple[str, SourceMatch]], mapping_path: Path, *, command: str = "apply"
) -> None:
    """Explain exactly which columns block the merge; write nothing (spec §5)."""

    print(
        f"✗ {command} durdu: {len(pending)} eşleştirme hâlâ onay bekliyor (review). "
        "Kör birleştirme yapılmaz."
    )
    for target_column, source in pending:
        column = source.column if source.column is not None else "(sütun seçilmedi)"
        line = f"  - {target_column} ← {source.file}:{column} (confidence {source.confidence:.2f})"
        if source.reason:
            line += f" — {source.reason}"
        print(line)
    print(
        f"→ {mapping_path} içindeki bu satırları düzenle "
        f"(status: auto veya unmatched), sonra tekrar: merger {command}"
    )
    print("Hiçbir çıktı dosyası yazılmadı.")


def _resolve_schema_path(target_schema: Path | None, mapping_path: Path) -> Path:
    """Use ``--target-schema`` or the schema.yaml sitting next to the mapping."""

    if target_schema is not None:
        return target_schema
    for candidate in (mapping_path.parent / DEFAULT_SCHEMA_NAME, Path(DEFAULT_SCHEMA_NAME)):
        if candidate.is_file():
            return candidate
    raise ContractValidationError(
        f"Hedef şema bulunamadı: '{DEFAULT_SCHEMA_NAME}' mapping klasöründe ya da "
        "çalışma klasöründe yok. --target-schema ile yolunu ver."
    )


def _resolve_source_files(mapping: MappingContract, mapping_path: Path) -> list[Path]:
    """Locate the files named in the plan, preferring the mapping's own folder.

    ``mapping.yaml`` records portable file names, so the same plan stays valid
    when a folder is moved. ``--inputs`` overrides this for sources kept
    elsewhere.
    """

    names: list[str] = []
    for entry in mapping.entries:
        for source in entry.sources:
            if source.file not in names:
                names.append(source.file)
    if not names:
        raise TransformError(f"'{mapping_path}' hiçbir kaynak dosya içermiyor.")

    resolved: list[Path] = []
    missing: list[str] = []
    for name in names:
        for candidate in (mapping_path.parent / name, Path(name), mapping_path.parent / Path(name).name):
            if candidate.is_file():
                resolved.append(candidate)
                break
        else:
            missing.append(name)
    if missing:
        raise TransformError(
            "Kaynak dosya bulunamadı: "
            + ", ".join(missing)
            + ". --inputs ile dosya yollarını ver."
        )
    return resolved


def _configure_utf8_stdout() -> None:
    """Allow the documented Unicode summary to work in Windows shells too."""

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        # Pytest's capture stream and some embedded hosts are already text-only.
        pass


if __name__ == "__main__":
    raise SystemExit(main())
