"""Deterministic consistency checks run between ``transform`` and ``write``.

The validator is a **second pair of eyes** on the matcher's decision (spec §7).
It never asks an LLM anything and it never repairs data: it reads the merged
table plus its provenance, reports what looks wrong, and pushes the mappings
behind a serious finding back to ``review`` so ``apply`` stops instead of
merging blindly (spec §14).

Four families of checks are implemented, all deterministic:

``type``
    The merged column has the dtype its target type asks for, and values the
    transformer could not convert (counted, never dropped) are reported.  A high
    conversion-failure ratio means the matcher very likely mapped the wrong
    column, so it is an error rather than a warning.

``null``
    A "null explosion": a target column that *was* mapped in a source file but
    still comes out empty there.  Rows from files where the column was never
    mapped are excluded, because those nulls are the plan, not a defect.

``outlier``
    Numeric columns get a coarse IQR fence and date columns a plausible-year
    range.  Both are warnings: an outlier is a value worth a human's eye, not
    proof of a bad mapping.

``required``
    A ``required: true`` target that is unmapped, or that carries any null at
    all, is an error — the target schema says every merged row must have it.

Severity decides what happens next: ``error`` blocks the merge, ``warning`` and
``info`` only travel to ``merge_report.xlsx``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
import re
from typing import Iterable, Sequence

import polars as pl

from core.contracts import MappingContract, SchemaContract
from core.transformer import PROVENANCE_SEPARATOR, TransformationResult
from core.types import MappingEntry, SourceMatch, TargetColumn


#: Severity levels, ordered from least to most serious.
SEVERITIES = ("info", "warning", "error")

#: Findings at or above this severity stop ``apply``.
BLOCKING_SEVERITY = "error"

#: Expected polars dtype per target type, mirroring the transformer's cast.
_EXPECTED_DTYPES: dict[str, pl.DataType] = {
    "string": pl.String,
    "integer": pl.Int64,
    "decimal": pl.Float64,
    "date": pl.Date,
    "boolean": pl.Boolean,
}

_TR_DECIMAL = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})*,\d+$")
_EN_DECIMAL = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})*\.\d+$")

#: How many sample values a finding carries into the report.
_SAMPLE_LIMIT = 3


class ValidationError(ValueError):
    """Raised when the validator cannot inspect the data it was handed."""


@dataclass(frozen=True)
class ValidationSettings:
    """Thresholds for the coarse, deterministic checks.

    Defaults are deliberately forgiving: the validator should flag a mapping
    that is obviously wrong, not argue about ordinary messy data.
    """

    #: Null ratio (over *mapped* rows) above which a column is flagged.
    null_warning_ratio: float = 0.5
    #: Conversion-failure ratio at or above which a mapping is an error.
    conversion_error_ratio: float = 0.2
    #: Multiplier for the inter-quartile fence used to spot outliers.
    outlier_iqr_factor: float = 3.0
    #: Fewer non-null numeric rows than this and the fence is not computed.
    min_outlier_rows: int = 8
    #: Dates before this year are reported as implausible.
    min_date_year: int = 1900
    #: Dates after this year are reported; ``None`` means "next year".
    max_date_year: int | None = None

    def __post_init__(self) -> None:
        for name in ("null_warning_ratio", "conversion_error_ratio"):
            value = getattr(self, name)
            if not 0.0 <= float(value) <= 1.0:
                raise ValidationError(f"{name} 0 ile 1 arasında olmalı.")
        if self.outlier_iqr_factor <= 0:
            raise ValidationError("outlier_iqr_factor pozitif olmalı.")
        if self.min_outlier_rows < 4:
            raise ValidationError("min_outlier_rows en az 4 olmalı (çeyreklik hesabı için).")


@dataclass(frozen=True)
class ValidationFinding:
    """One thing the validator noticed, addressed to a human.

    ``source_file``/``source_column`` are filled when the finding blames a
    specific mapping line; that is what :func:`downgrade_to_review` acts on.
    """

    check: str
    severity: str
    target_column: str
    message: str
    source_file: str | None = None
    source_column: str | None = None
    metric: float | None = None
    count: int | None = None
    samples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValidationError(f"Geçersiz severity: {self.severity!r}.")

    @property
    def is_blocking(self) -> bool:
        return self.severity == BLOCKING_SEVERITY

    def describe(self) -> str:
        """One human-readable line, used by the CLI and the report."""

        where = self.target_column
        if self.source_file is not None:
            column = self.source_column if self.source_column is not None else "(sütun yok)"
            where += f" ← {self.source_file}:{column}"
        return f"[{self.check}] {where}: {self.message}"


@dataclass(frozen=True)
class ValidationReport:
    """Everything the validator found in one merge run."""

    findings: tuple[ValidationFinding, ...] = ()
    settings: ValidationSettings = field(default_factory=ValidationSettings)

    @property
    def errors(self) -> list[ValidationFinding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def warnings(self) -> list[ValidationFinding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    @property
    def blocking(self) -> bool:
        """Whether these findings must stop ``apply`` before anything is written."""

        return any(finding.is_blocking for finding in self.findings)

    def for_column(self, target_column: str) -> list[ValidationFinding]:
        return [finding for finding in self.findings if finding.target_column == target_column]


def validate(
    result: TransformationResult,
    mapping: MappingContract,
    schema: SchemaContract,
    *,
    settings: ValidationSettings | None = None,
) -> ValidationReport:
    """Audit a transformed table against its plan and target schema.

    Nothing in ``result`` is modified: the validator only reads (spec §7/§14).
    """

    options = settings or ValidationSettings()
    entries = {entry.target_column: entry for entry in mapping.entries}
    findings: list[ValidationFinding] = []

    for column in schema.target_columns:
        if column.name not in result.dataframe.columns:
            raise ValidationError(
                f"Hedef sütun '{column.name}' birleşik veride yok; validator çalıştırılamaz."
            )
        entry = entries.get(column.name)
        findings.extend(_check_type(result, column, entry, options))
        findings.extend(_check_nulls(result, column, entry, options))
        findings.extend(_check_outliers(result, column, options))
        findings.extend(_check_required(result, column, entry))

    return ValidationReport(findings=tuple(findings), settings=options)


def downgrade_to_review(mapping: MappingContract, report: ValidationReport) -> MappingContract:
    """Return the plan with every mapping behind an error pushed to ``review``.

    The validator does not touch the data and does not rewrite the user's file;
    it hands back a plan in which the suspicious lines are no longer ``auto``.
    ``apply`` shows those lines and refuses to merge, which is exactly what the
    Phase-1 review guard already does for an unreviewed match (spec §5).
    """

    blamed = _blamed_sources(report)
    if not blamed:
        return mapping

    entries: list[MappingEntry] = []
    for entry in mapping.entries:
        reasons = blamed.get(entry.target_column)
        if not reasons:
            entries.append(entry)
            continue
        sources = [_downgrade_source(source, reasons) for source in entry.sources]
        entries.append(MappingEntry(target_column=entry.target_column, sources=sources))
    return MappingContract(entries=entries)


def review_targets(report: ValidationReport) -> list[tuple[str, ValidationFinding]]:
    """``(target_column, finding)`` for every error, in report order."""

    return [(finding.target_column, finding) for finding in report.errors]


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


def _check_type(
    result: TransformationResult,
    column: TargetColumn,
    entry: MappingEntry | None,
    settings: ValidationSettings,
) -> list[ValidationFinding]:
    """Dtype agreement plus the conversion failures the transformer counted."""

    findings: list[ValidationFinding] = []
    expected = _EXPECTED_DTYPES[column.type]
    actual = result.dataframe.schema[column.name]
    if actual != expected:
        findings.append(
            ValidationFinding(
                check="type",
                severity="error",
                target_column=column.name,
                message=(
                    f"hedef tür {column.type} ({expected}) bekliyor, birleşik veri {actual} taşıyor."
                ),
            )
        )

    errors = result.conversion_error_counts.get(column.name, 0)
    if errors:
        mapped = _mapped_row_count(result, column.name)
        ratio = errors / mapped if mapped else 1.0
        severity = "error" if ratio >= settings.conversion_error_ratio else "warning"
        findings.append(
            ValidationFinding(
                check="type",
                severity=severity,
                target_column=column.name,
                message=(
                    f"{errors} değer {column.type} türüne dönüştürülemedi "
                    f"(eşlenen {mapped} satırın %{ratio * 100:.1f}'i); "
                    "kaynak sütunun türü hedefle uyumsuz olabilir."
                ),
                source_file=_single_source_file(entry),
                source_column=_single_source_column(entry),
                metric=round(ratio, 6),
                count=errors,
            )
        )
    findings.extend(_check_mixed_decimal_format(result, column))
    return findings


def _check_mixed_decimal_format(
    result: TransformationResult, column: TargetColumn
) -> list[ValidationFinding]:
    """Numbers left in two different notations inside one text column.

    TR/EN normalization only runs for numeric targets, so a ``string`` column can
    still end up holding both ``1.234,56`` and ``1,234.56``.  That is a format
    defect a human must resolve; the validator reports it and changes nothing.
    """

    if column.type != "string":
        return []
    turkish: list[str] = []
    english: list[str] = []
    for value in result.dataframe[column.name].drop_nulls().to_list():
        text = str(value).strip()
        if _TR_DECIMAL.fullmatch(text):
            turkish.append(text)
        elif _EN_DECIMAL.fullmatch(text):
            english.append(text)
    if not turkish or not english:
        return []
    return [
        ValidationFinding(
            check="format",
            severity="warning",
            target_column=column.name,
            message=(
                f"aynı sütunda karışık ondalık biçimi: {len(turkish)} TR ({turkish[0]}), "
                f"{len(english)} EN ({english[0]}). Hedef tür string olduğu için "
                "normalizasyon uygulanmadı."
            ),
            count=len(turkish) + len(english),
            samples=tuple(turkish[:1] + english[:1]),
        )
    ]


def _check_nulls(
    result: TransformationResult,
    column: TargetColumn,
    entry: MappingEntry | None,
    settings: ValidationSettings,
) -> list[ValidationFinding]:
    """Null explosion, measured only where the column was actually mapped.

    A file that never mapped this target contributes planned nulls, so counting
    them would flag every partial mapping.  What matters is a source that *was*
    mapped and still produced nothing.
    """

    findings: list[ValidationFinding] = []
    for (source_file, source_column), (rows, nulls) in _null_counts_by_source(
        result, column.name
    ).items():
        if not rows:
            continue
        ratio = nulls / rows
        if nulls == rows:
            severity = "error"
            message = (
                f"eşlenen kaynak sütun tamamen boş: {rows} satırın hepsi null. "
                "Büyük olasılıkla yanlış sütun eşleşti."
            )
        elif ratio > settings.null_warning_ratio:
            severity = "warning"
            message = (
                f"null patlaması: {nulls}/{rows} satır boş "
                f"(%{ratio * 100:.1f}), eşik %{settings.null_warning_ratio * 100:.0f}."
            )
        else:
            continue
        findings.append(
            ValidationFinding(
                check="null",
                severity=severity,
                target_column=column.name,
                message=message,
                source_file=source_file,
                source_column=source_column,
                metric=round(ratio, 6),
                count=nulls,
            )
        )
    return findings


def _check_outliers(
    result: TransformationResult, column: TargetColumn, settings: ValidationSettings
) -> list[ValidationFinding]:
    """A coarse fence for numbers and a plausible-year range for dates."""

    values = result.dataframe[column.name].drop_nulls().to_list()
    if column.type in ("integer", "decimal"):
        return _numeric_outliers(column, values, settings)
    if column.type == "date":
        return _date_outliers(column, values, settings)
    return []


def _numeric_outliers(
    column: TargetColumn, values: Sequence[object], settings: ValidationSettings
) -> list[ValidationFinding]:
    numbers = sorted(float(value) for value in values if isinstance(value, (int, float, Decimal)))
    if len(numbers) < settings.min_outlier_rows:
        return []
    first = _quantile(numbers, 0.25)
    third = _quantile(numbers, 0.75)
    spread = third - first
    if spread <= 0:
        return []
    low = first - settings.outlier_iqr_factor * spread
    high = third + settings.outlier_iqr_factor * spread
    outliers = [number for number in numbers if number < low or number > high]
    if not outliers:
        return []
    return [
        ValidationFinding(
            check="outlier",
            severity="warning",
            target_column=column.name,
            message=(
                f"{len(outliers)} aykırı değer beklenen aralığın dışında "
                f"[{low:g}, {high:g}] (IQR×{settings.outlier_iqr_factor:g}); "
                f"en uçtakiler: {_format_samples(outliers)}."
            ),
            metric=round(max(abs(number) for number in outliers), 6),
            count=len(outliers),
            samples=tuple(_sample_texts(outliers)),
        )
    ]


def _date_outliers(
    column: TargetColumn, values: Sequence[object], settings: ValidationSettings
) -> list[ValidationFinding]:
    maximum_year = settings.max_date_year if settings.max_date_year is not None else date.today().year + 1
    dates = [value for value in values if isinstance(value, date)]
    outliers = [
        value for value in dates if value.year < settings.min_date_year or value.year > maximum_year
    ]
    if not outliers:
        return []
    return [
        ValidationFinding(
            check="outlier",
            severity="warning",
            target_column=column.name,
            message=(
                f"{len(outliers)} tarih {settings.min_date_year}-{maximum_year} aralığının "
                f"dışında: {_format_samples(outliers)}. Gün/ay sırası karışmış olabilir."
            ),
            count=len(outliers),
            samples=tuple(_sample_texts(outliers)),
        )
    ]


def _check_required(
    result: TransformationResult, column: TargetColumn, entry: MappingEntry | None
) -> list[ValidationFinding]:
    """A required target must be mapped and must be filled in every row."""

    if not column.required:
        return []
    usable = [
        source
        for source in (entry.sources if entry is not None else [])
        if source.status != "unmatched" and source.column is not None
    ]
    if not usable:
        return [
            ValidationFinding(
                check="required",
                severity="error",
                target_column=column.name,
                message=(
                    "zorunlu hedef sütun hiçbir kaynak dosyaya eşlenmedi; "
                    "mapping.yaml'da bir kaynak sütun seç."
                ),
            )
        ]
    nulls = result.dataframe[column.name].null_count()
    if not nulls:
        return []
    rows = result.dataframe.height
    return [
        ValidationFinding(
            check="required",
            severity="error",
            target_column=column.name,
            message=(
                f"zorunlu hedef sütunda {nulls}/{rows} satır boş; "
                "required: true her satırda değer bekler."
            ),
            metric=round(nulls / rows, 6) if rows else 1.0,
            count=nulls,
        )
    ]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _null_counts_by_source(
    result: TransformationResult, target_column: str
) -> dict[tuple[str, str], tuple[int, int]]:
    """``(file, source_column) -> (rows, nulls)`` for mapped rows only.

    Deduplicated rows can carry several origins joined with ``"; "``; those rows
    stand for more than one source and are left out of this per-source ratio
    rather than being attributed to a file they only partly came from.
    """

    counts: dict[tuple[str, str], list[int]] = {}
    values = result.dataframe[target_column].to_list()
    files = result.provenance["source_file"].to_list()
    columns = result.provenance[target_column].to_list()
    for value, source_file, source_column in zip(values, files, columns):
        if source_column is None or source_file is None:
            continue
        if PROVENANCE_SEPARATOR in str(source_file) or PROVENANCE_SEPARATOR in str(source_column):
            continue
        key = (str(source_file), str(source_column))
        entry = counts.setdefault(key, [0, 0])
        entry[0] += 1
        if value is None:
            entry[1] += 1
    return {key: (rows, nulls) for key, (rows, nulls) in counts.items()}


def _mapped_row_count(result: TransformationResult, target_column: str) -> int:
    """Rows whose provenance says this target was mapped to a source column."""

    return int(result.provenance[target_column].is_not_null().sum())


def _single_source_file(entry: MappingEntry | None) -> str | None:
    """The one file to blame, or ``None`` when the target has several."""

    sources = _usable_sources(entry)
    return sources[0].file if len(sources) == 1 else None


def _single_source_column(entry: MappingEntry | None) -> str | None:
    sources = _usable_sources(entry)
    return sources[0].column if len(sources) == 1 else None


def _usable_sources(entry: MappingEntry | None) -> list[SourceMatch]:
    if entry is None:
        return []
    return [source for source in entry.sources if source.column is not None and source.status != "unmatched"]


def _blamed_sources(report: ValidationReport) -> dict[str, list[ValidationFinding]]:
    blamed: dict[str, list[ValidationFinding]] = {}
    for finding in report.errors:
        blamed.setdefault(finding.target_column, []).append(finding)
    return blamed


def _downgrade_source(source: SourceMatch, findings: Sequence[ValidationFinding]) -> SourceMatch:
    """Push one mapping line to ``review`` when a finding points at it.

    A finding naming a file and column downgrades only that line; a finding about
    the target column as a whole downgrades every ``auto`` line of the target.
    """

    matching = [
        finding
        for finding in findings
        if finding.source_file is None
        or (finding.source_file == source.file and finding.source_column == source.column)
    ]
    if not matching or source.status != "auto":
        return source
    reason = "; ".join(finding.message for finding in matching)
    existing = f"{source.reason} | " if source.reason else ""
    return replace(source, status="review", reason=f"{existing}validator: {reason}")


def _quantile(sorted_values: Sequence[float], quantile: float) -> float:
    """Linear-interpolated quantile of an already sorted, non-empty sequence."""

    if not sorted_values:
        raise ValidationError("Çeyreklik için en az bir değer gerekli.")
    position = (len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _sample_texts(values: Iterable[object]) -> list[str]:
    items = list(values)
    if len(items) <= _SAMPLE_LIMIT:
        chosen = items
    else:
        # Both ends are informative for an outlier list, which arrives sorted.
        chosen = items[: _SAMPLE_LIMIT - 1] + items[-1:]
    return [f"{value:g}" if isinstance(value, float) else str(value) for value in chosen]


def _format_samples(values: Iterable[object]) -> str:
    return ", ".join(_sample_texts(values))
