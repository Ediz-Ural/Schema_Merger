"""Deterministic value normalization used while transforming source rows.

The profiler deliberately keeps source values untouched.  This module is the
separate, explicit conversion boundary used for values written to the target
schema.  A conversion either returns a typed value or raises
``NormalizationError``; callers must record the latter rather than discard the
source value silently.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Literal

import pandas as pd


TargetType = Literal["string", "integer", "decimal", "date", "boolean"]


class NormalizationError(ValueError):
    """Raised when a non-empty source value cannot fit its target type."""


_INTEGER = re.compile(r"^[+-]?\d+$")
_TR_GROUPED_DECIMAL = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})+,\d+$")
_EN_GROUPED_DECIMAL = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+\.\d+$")
_TR_DECIMAL = re.compile(r"^[+-]?\d+,\d+$")
_EN_DECIMAL = re.compile(r"^[+-]?\d+\.\d+$")
_TR_DATE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")
_SLASH_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_TRUE_VALUES = {"true", "yes", "evet", "1"}
_FALSE_VALUES = {"false", "no", "hayir", "hayır", "0"}


def normalize_value(value: object, target_type: TargetType) -> object | None:
    """Convert one value to a documented target type.

    Blank and missing values are represented as ``None``.  Invalid *non-blank*
    values raise an exception so the transformer can retain the row and count
    the conversion failure.
    """

    if is_missing(value):
        return None
    if target_type == "string":
        return str(value)
    if target_type == "decimal":
        return float(normalize_decimal(value))
    if target_type == "integer":
        decimal = normalize_decimal(value)
        if decimal != decimal.to_integral_value():
            raise NormalizationError(f"{value!r} is not an integer")
        return int(decimal)
    if target_type == "date":
        return normalize_date(value)
    if target_type == "boolean":
        return normalize_boolean(value)
    raise NormalizationError(f"Unsupported target type: {target_type!r}")


def normalize_decimal(value: object) -> Decimal:
    """Parse Turkish and English decimal formats without locale state.

    Examples: ``12,50`` becomes ``12.50`` and ``1.234,56`` becomes
    ``1234.56``.  English grouped decimals (``1,234.56``) are also accepted.
    """

    if isinstance(value, bool):
        raise NormalizationError(f"{value!r} is not a decimal")
    if isinstance(value, Decimal):
        decimal = value
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise NormalizationError(f"{value!r} is not a finite decimal")
        decimal = Decimal(str(value))
    else:
        text = str(value).strip().replace("\u00a0", "").replace(" ", "")
        if _INTEGER.fullmatch(text) or _EN_DECIMAL.fullmatch(text):
            normalized = text
        elif _TR_GROUPED_DECIMAL.fullmatch(text):
            normalized = text.replace(".", "").replace(",", ".")
        elif _EN_GROUPED_DECIMAL.fullmatch(text):
            normalized = text.replace(",", "")
        elif _TR_DECIMAL.fullmatch(text):
            normalized = text.replace(",", ".")
        else:
            raise NormalizationError(f"{value!r} is not a supported decimal format")
        try:
            decimal = Decimal(normalized)
        except InvalidOperation as error:
            raise NormalizationError(f"{value!r} is not a decimal") from error
    if not decimal.is_finite():
        raise NormalizationError(f"{value!r} is not a finite decimal")
    return decimal


def normalize_date(value: object) -> date:
    """Return a date for ISO, Turkish ``gg.aa.yyyy``, or slash dates."""

    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        if _TR_DATE.fullmatch(text):
            return datetime.strptime(text, "%d.%m.%Y").date()
        if _SLASH_DATE.fullmatch(text):
            return datetime.strptime(text, "%d/%m/%Y").date()
        # ``fromisoformat`` also handles an ISO datetime while keeping its date.
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as error:
        raise NormalizationError(f"{value!r} is not a supported date format") from error


def normalize_boolean(value: object) -> bool:
    """Parse booleans and the Turkish/English text forms used by profiling."""

    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise NormalizationError(f"{value!r} is not a boolean")


def is_missing(value: object) -> bool:
    """Recognise pandas, Python, and blank-string missing values safely."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    try:
        return bool(missing)
    except (TypeError, ValueError):
        # Array-like values are not scalar table cells and are therefore not
        # interpreted as a missing scalar here.
        return False
