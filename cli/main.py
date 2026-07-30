"""CLI entry point for profiling inputs and producing mapping plans."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from core.contracts import ContractValidationError, dump_mapping, load_schema
from core.llm import LLMClient, LLMConfigurationError, create_llm_client
from core.matcher import match_profiles
from core.profiler import ProfileError, profile_file


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
    return parser


def main(argv: list[str] | None = None, *, llm_client: LLMClient | None = None) -> int:
    """Run a command.

    ``llm_client`` is an injection point for tests. Normal CLI invocations
    construct the configured client only for the ``analyze`` command.
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


def _configure_utf8_stdout() -> None:
    """Allow the documented Unicode summary to work in Windows shells too."""

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        # Pytest's capture stream and some embedded hosts are already text-only.
        pass


if __name__ == "__main__":
    raise SystemExit(main())
