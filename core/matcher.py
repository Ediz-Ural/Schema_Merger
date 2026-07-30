"""LLM-assisted, plan-only matching from column profiles to a target schema.

The matcher sends one compact metadata request per input file.  It never sends
or changes full data rows, and it never calls an LLM while iterating rows.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.contracts import MappingContract, SchemaContract
from core.llm import LLMClient
from core.types import ColumnProfile, FileProfile, MappingEntry, SourceMatch, TableProfile, TargetColumn


DEFAULT_AUTO_CONFIDENCE = 0.85
MAX_PROMPT_SAMPLES = 10

_SYSTEM_PROMPT = """You match source table columns to a target schema for a vertical union plan.
Return only JSON. Do not transform, generate, or write data rows. For every target column,
select at most one source column from the supplied file or null if no match exists.
Use names, inferred types, samples, and statistics. The exact JSON shape is:
{"matches":[{"target_column":"...","column":"source_name or null","confidence":0.0,"reason":"..."}]}.
Confidence must be between 0 and 1. Do not propose horizontal joins."""


@dataclass(frozen=True)
class MatchThresholds:
    """Deterministic status policy applied after the LLM proposes a column.

    A confidence of ``auto_confidence`` (default 0.85) or greater becomes
    ``auto``. A valid lower-confidence proposal is always ``review``. A null
    proposal is ``unmatched``. Invalid or incomplete LLM output is ``review``
    even if it includes a high confidence value.
    """

    auto_confidence: float = DEFAULT_AUTO_CONFIDENCE

    def __post_init__(self) -> None:
        if not 0.0 <= self.auto_confidence <= 1.0:
            raise ValueError("auto_confidence must be between 0 and 1")


@dataclass
class Matcher:
    """Build a mapping plan from source profiles using a provider-neutral LLM."""

    llm: LLMClient
    thresholds: MatchThresholds = MatchThresholds()

    def match(self, source_profiles: Sequence[FileProfile], schema: SchemaContract) -> MappingContract:
        """Return one source proposal per target column and input file.

        Exactly one ``complete`` call is made for each item in ``source_profiles``.
        Therefore request count is independent of each file's row count.
        """

        candidates_by_target: dict[str, list[SourceMatch]] = {
            target.name: [] for target in schema.target_columns
        }
        for source_file in source_profiles:
            candidates = _columns_for_file(source_file)
            response = self.llm.complete(_SYSTEM_PROMPT, _build_user_prompt(schema.target_columns, source_file, candidates))
            decisions, error = _parse_decisions(response, schema.target_columns, candidates)
            for target in schema.target_columns:
                candidates_by_target[target.name].append(
                    _source_match_for_target(
                        source_file=source_file,
                        target=target,
                        candidates=candidates,
                        decision=decisions.get(target.name),
                        parse_error=error,
                        thresholds=self.thresholds,
                    )
                )
        return MappingContract(
            entries=[
                MappingEntry(target_column=target.name, sources=candidates_by_target[target.name])
                for target in schema.target_columns
            ]
        )


def match_profiles(
    source_profiles: Sequence[FileProfile],
    schema: SchemaContract,
    llm: LLMClient,
    *,
    thresholds: MatchThresholds | None = None,
) -> MappingContract:
    """Convenience wrapper for :class:`Matcher`."""

    return Matcher(llm=llm, thresholds=thresholds or MatchThresholds()).match(source_profiles, schema)


def _columns_for_file(source_file: FileProfile) -> list[ColumnProfile]:
    """Flatten worksheet metadata; a mapping contract identifies the input file."""

    return [column for table in source_file.tables for column in table.columns]


def _build_user_prompt(
    targets: Iterable[TargetColumn], source_file: FileProfile, candidates: Iterable[ColumnProfile]
) -> str:
    """Serialize profile metadata only, capped at 10 examples per source column."""

    document = {
        "input_file": Path(source_file.path).name,
        "target_columns": [
            {"name": target.name, "type": target.type, "required": target.required} for target in targets
        ],
        "source_columns": [_column_context(column) for column in candidates],
    }
    return json.dumps(document, ensure_ascii=False, default=str)


def _column_context(column: ColumnProfile) -> dict[str, Any]:
    return {
        "name": column.name,
        "inferred_type": column.inferred_type,
        "samples": column.samples[:MAX_PROMPT_SAMPLES],
        "statistics": {
            "unique_count": column.unique_count,
            "null_ratio": column.null_ratio,
            "minimum": column.minimum,
            "maximum": column.maximum,
            "format_pattern": column.format_pattern,
        },
    }


def _parse_decisions(
    response: str, targets: Sequence[TargetColumn], candidates: Sequence[ColumnProfile]
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Parse a complete LLM response without trusting its shape or values."""

    try:
        document = json.loads(_strip_json_fence(response))
    except (TypeError, json.JSONDecodeError):
        return {}, "LLM yanıtı geçerli JSON değil."
    if not isinstance(document, dict) or not isinstance(document.get("matches"), list):
        return {}, "LLM yanıtında 'matches' listesi yok."

    target_names = {target.name for target in targets}
    candidate_names = {candidate.name for candidate in candidates}
    decisions: dict[str, dict[str, Any]] = {}
    for item in document["matches"]:
        if not isinstance(item, dict):
            continue
        target_name = item.get("target_column")
        if target_name not in target_names or target_name in decisions:
            continue
        column = item.get("column")
        confidence = item.get("confidence")
        reason = item.get("reason")
        if column is not None and (not isinstance(column, str) or column not in candidate_names):
            continue
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            continue
        if not 0.0 <= float(confidence) <= 1.0 or not isinstance(reason, str) or not reason.strip():
            continue
        decisions[target_name] = {
            "column": column,
            "confidence": float(confidence),
            "reason": reason.strip(),
        }
    return decisions, None


def _strip_json_fence(response: str) -> str:
    text = response.strip()
    if text.startswith("```") and text.endswith("```"):
        return text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return text


def _source_match_for_target(
    *,
    source_file: FileProfile,
    target: TargetColumn,
    candidates: Sequence[ColumnProfile],
    decision: dict[str, Any] | None,
    parse_error: str | None,
    thresholds: MatchThresholds,
) -> SourceMatch:
    file_name = Path(source_file.path).name
    if parse_error is not None:
        return _review_match(file_name, None, [], parse_error)
    if decision is None:
        return _review_match(
            file_name,
            None,
            [],
            f"LLM yanıtında '{target.name}' için geçerli eşleştirme yok.",
        )
    column_name = decision["column"]
    if column_name is None:
        return SourceMatch(
            file=file_name,
            column=None,
            confidence=decision["confidence"],
            status="unmatched",
            reason=decision["reason"],
            samples=[],
        )
    column = next(column for column in candidates if column.name == column_name)
    confidence = decision["confidence"]
    if confidence >= thresholds.auto_confidence:
        return SourceMatch(
            file=file_name,
            column=column.name,
            confidence=confidence,
            status="auto",
            reason=decision["reason"],
        )
    return _review_match(file_name, column.name, column.samples[:MAX_PROMPT_SAMPLES], decision["reason"], confidence)


def _review_match(
    file_name: str,
    column: str | None,
    samples: list[object],
    reason: str,
    confidence: float = 0.0,
) -> SourceMatch:
    return SourceMatch(
        file=file_name,
        column=column,
        confidence=confidence,
        status="review",
        reason=reason,
        samples=samples,
    )
