"""Deterministic CSV/XLSX profiling with basic Turkish/English type detection.

For multi-sheet Excel workbooks, :func:`profile_file` profiles every worksheet by
default. Pass ``sheet`` to profile one named worksheet. Source values are never
rewritten; normalization below is used only to infer a column's profile.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

import pandas as pd
from pandas.api.types import is_bool_dtype

from .types import ColumnProfile, FileProfile, TableProfile


DEFAULT_SAMPLE_SIZE = 5
_TR_DATE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")
_SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}(?:[ T].*)?$")
_INTEGER = re.compile(r"^[+-]?\d+$")
_BOOLEAN_TEXT = {"true", "false", "yes", "no", "evet", "hayir", "hayır"}


class ProfileError(ValueError):
    """Raised when a file cannot be read or its format is unsupported."""


def profile_file(
    input_path: str | Path,
    *,
    sheet: str | None = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> FileProfile:
    """Profile a `.csv` or `.xlsx` file without transforming its source data.

    Excel workbooks are treated as a collection of source tables: every worksheet
    is profiled unless ``sheet`` names one worksheet. ``sheet`` is invalid for CSV
    files. ``sample_size`` controls how many leading non-null values are retained.
    """
    path = Path(input_path)
    if sample_size < 1:
        raise ProfileError("sample_size must be at least 1")
    if not path.is_file():
        raise ProfileError(f"Input file does not exist or is not a file: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        if sheet is not None:
            raise ProfileError("--sheet can only be used with .xlsx input files")
        dataframe = _read_csv(path)
        return FileProfile(path=path, tables=[profile_dataframe(dataframe, path.stem, sample_size)])
    if suffix != ".xlsx":
        raise ProfileError(
            f"Unsupported input format '{path.suffix or '<none>'}'. Only .csv and .xlsx are supported."
        )

    try:
        workbooks = pd.read_excel(path, sheet_name=None, dtype=object, engine="openpyxl")
    except Exception as error:  # pandas/openpyxl exceptions vary by corruption type
        raise ProfileError(f"Could not read Excel file '{path}': {error}") from error

    if sheet is not None:
        if sheet not in workbooks:
            available = ", ".join(str(name) for name in workbooks) or "(none)"
            raise ProfileError(f"Worksheet '{sheet}' was not found. Available worksheets: {available}")
        workbooks = {sheet: workbooks[sheet]}

    return FileProfile(
        path=path,
        tables=[profile_dataframe(frame, str(name), sample_size) for name, frame in workbooks.items()],
    )


def profile_dataframe(dataframe: pd.DataFrame, table_name: str, sample_size: int = DEFAULT_SAMPLE_SIZE) -> TableProfile:
    """Return deterministic column profiles for an already loaded table."""
    return TableProfile(
        name=table_name,
        row_count=len(dataframe),
        columns=[_profile_column(str(name), dataframe[name], sample_size) for name in dataframe.columns],
    )


def _read_csv(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                preview = handle.read(4096)
            try:
                delimiter = csv.Sniffer().sniff(preview, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
            return pd.read_csv(path, dtype=object, encoding=encoding, sep=delimiter)
        except (UnicodeDecodeError, pd.errors.ParserError, OSError) as error:
            last_error = error
    raise ProfileError(f"Could not read CSV file '{path}': {last_error}") from last_error


def _profile_column(name: str, series: pd.Series, sample_size: int) -> ColumnProfile:
    non_null = series[series.notna()]
    values = list(non_null)
    inferred_type, normalized_values, pattern = _infer_type(values, series)
    samples = [_display_value(value) for value in values[:sample_size]]
    minimum: object | None = None
    maximum: object | None = None
    if normalized_values:
        minimum = _display_value(min(normalized_values))
        maximum = _display_value(max(normalized_values))
    return ColumnProfile(
        name=name,
        inferred_type=inferred_type,
        samples=samples,
        unique_count=int(non_null.nunique(dropna=True)),
        null_ratio=float(series.isna().mean()) if len(series) else 0.0,
        minimum=minimum,
        maximum=maximum,
        format_pattern=pattern,
    )


def _infer_type(values: list[object], series: pd.Series) -> tuple[str, list[object], str | None]:
    if not values:
        return "string", [], None
    if is_bool_dtype(series) or all(isinstance(value, bool) for value in values):
        return "boolean", [], "boolean"

    boolean_text = [_text(value).casefold() for value in values]
    if all(value in _BOOLEAN_TEXT for value in boolean_text):
        return "boolean", [], "boolean_text"

    dates, date_pattern = _parse_dates(values)
    if dates is not None:
        return "date", dates, date_pattern

    decimals, numeric_pattern = _parse_decimals(values)
    if decimals is not None:
        if all(value == value.to_integral_value() for value in decimals):
            return "integer", [int(value) for value in decimals], numeric_pattern or "integer"
        return "decimal", [float(value) for value in decimals], numeric_pattern
    return "string", [], None


def _parse_dates(values: Iterable[object]) -> tuple[list[datetime] | None, str | None]:
    parsed: list[datetime] = []
    patterns: set[str] = set()
    for value in values:
        if isinstance(value, pd.Timestamp):
            parsed.append(value.to_pydatetime())
            patterns.add("excel_date")
            continue
        if isinstance(value, datetime):
            parsed.append(value)
            patterns.add("excel_date")
            continue
        if isinstance(value, date):
            parsed.append(datetime.combine(value, datetime.min.time()))
            patterns.add("excel_date")
            continue
        text = _text(value)
        if _ISO_DATE.fullmatch(text):
            patterns.add("iso_date")
            dayfirst = False
        elif _TR_DATE.fullmatch(text):
            patterns.add("tr_date_dd.mm.yyyy")
            dayfirst = True
        elif _SLASH_DATE.fullmatch(text):
            patterns.add("date_dd/mm/yyyy")
            dayfirst = True
        else:
            return None, None
        try:
            parsed.append(pd.to_datetime(text, dayfirst=dayfirst, errors="raise").to_pydatetime())
        except (ValueError, TypeError, OverflowError):
            return None, None
    return parsed, next(iter(patterns)) if len(patterns) == 1 else "mixed_date"


def _parse_decimals(values: Iterable[object]) -> tuple[list[Decimal] | None, str | None]:
    parsed: list[Decimal] = []
    patterns: set[str] = set()
    for value in values:
        if isinstance(value, bool):
            return None, None
        if isinstance(value, (int, float, Decimal)) and not pd.isna(value):
            try:
                parsed.append(Decimal(str(value)))
                patterns.add("numeric")
                continue
            except InvalidOperation:
                return None, None
        text = _text(value)
        normalized, pattern = _normalise_number(text)
        if normalized is None:
            return None, None
        try:
            parsed.append(Decimal(normalized))
            patterns.add(pattern)
        except InvalidOperation:
            return None, None
    return parsed, next(iter(patterns)) if len(patterns) == 1 else "mixed_numeric"


def _normalise_number(text: str) -> tuple[str | None, str | None]:
    compact = text.replace("\u00a0", "").replace(" ", "")
    if not compact:
        return None, None
    if _INTEGER.fullmatch(compact):
        return compact, "integer"
    if "," in compact and "." in compact:
        if not re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+,\d+", compact):
            return None, None
        return compact.replace(".", "").replace(",", "."), "tr_decimal_grouped"
    if "," in compact:
        if not re.fullmatch(r"[+-]?\d+,\d+", compact):
            return None, None
        return compact.replace(",", "."), "tr_decimal"
    if re.fullmatch(r"[+-]?\d+\.\d+", compact):
        return compact, "en_decimal"
    return None, None


def _text(value: object) -> str:
    return str(value).strip()


def _display_value(value: object) -> object:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, str):
        try:
            return value.item()
        except ValueError:
            pass
    return value
