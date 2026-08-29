"""Deterministic second opinion on what a proposed match *means*.

The matcher can be confident and still wrong in a way types never reveal: a
line total is a decimal just like a unit price, and a price in dollars is a
decimal just like a price in lira.  Merging either one silently produces a
column whose numbers are not comparable.

These guards run after the LLM proposes and only ever lower trust -- an ``auto``
match becomes ``review`` so a human decides, never the model.  They
never approve, never rewrite a column, and never touch data.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from core.contracts import MappingContract
from core.types import ColumnProfile, FileProfile, MappingEntry, SourceMatch


#: Words that mark a value as "per one item".
UNIT_MARKERS = frozenset({"unit", "birim", "each", "per", "tekil", "piece", "adet"})

#: Words that mark a value as an aggregate over several items or rows.
AGGREGATE_MARKERS = frozenset(
    {
        "total", "toplam", "tutar", "subtotal", "aratoplam", "sum", "ciro",
        "gross", "brut", "net", "kdv", "vat", "tax", "revenue", "hasilat",
    }
)

#: Words that say the column is money at all; without one, the guard stays out.
MONEY_MARKERS = frozenset(
    {
        "price", "fiyat", "tutar", "amount", "cost", "ucret", "bedel",
        "total", "toplam", "revenue", "ciro", "hasilat", "maliyet",
    }
)

#: Currency spellings and symbols, mapped to the name shown in the reason.
CURRENCY_WORDS = {
    "tl": "TL", "try": "TL", "lira": "TL", "tely": "TL",
    "usd": "USD", "dolar": "USD", "dollar": "USD",
    "eur": "EUR", "euro": "EUR", "avro": "EUR",
    "gbp": "GBP", "sterlin": "GBP",
}
CURRENCY_SYMBOLS = {"₺": "TL", "$": "USD", "€": "EUR", "£": "GBP"}

#: How many sample values are attached to a match the guard sends to review.
MAX_REVIEW_SAMPLES = 10

_TOKEN = re.compile(r"[^0-9a-zçğıöşü]+")
_FOLD = str.maketrans("ÇĞİIÖŞÜ", "cgiiosu")


def apply_semantic_guards(
    mapping: MappingContract, profiles: Sequence[FileProfile]
) -> MappingContract:
    """Return the plan with risky ``auto`` matches demoted to ``review``."""

    columns = _columns_by_file(profiles)
    entries = [_guard_entry(entry, columns) for entry in mapping.entries]
    return MappingContract(entries=entries)


def _guard_entry(entry: MappingEntry, columns: dict[tuple[str, str], ColumnProfile]) -> MappingEntry:
    warnings: dict[int, str] = {}

    for index, source in enumerate(entry.sources):
        if source.status != "auto" or source.column is None:
            continue
        conflict = _aggregate_conflict(entry.target_column, source.column)
        if conflict is not None:
            warnings[index] = conflict

    for index, warning in _currency_conflicts(entry, columns).items():
        warnings.setdefault(index, warning)

    if not warnings:
        return entry
    return MappingEntry(
        target_column=entry.target_column,
        sources=[
            _demote(source, warnings[index], columns.get((source.file, source.column or "")))
            if index in warnings
            else source
            for index, source in enumerate(entry.sources)
        ],
    )


def _aggregate_conflict(target_column: str, source_column: str) -> str | None:
    """Flag a per-item target filled from an aggregate column, or the reverse."""

    target = _tokens(target_column)
    source = _tokens(source_column)
    if not (target & MONEY_MARKERS or source & MONEY_MARKERS):
        return None

    if (target & UNIT_MARKERS) and (source & AGGREGATE_MARKERS) and not (source & UNIT_MARKERS):
        return (
            f"'{source_column}' toplam/ara toplam anlamına gelebilir, "
            f"'{target_column}' ise birim başına bir değer bekliyor."
        )
    if (source & UNIT_MARKERS) and (target & AGGREGATE_MARKERS) and not (target & UNIT_MARKERS):
        return (
            f"'{source_column}' birim başına bir değer gibi görünüyor, "
            f"'{target_column}' ise toplam bekliyor."
        )
    return None


def _currency_conflicts(
    entry: MappingEntry, columns: dict[tuple[str, str], ColumnProfile]
) -> dict[int, str]:
    """Flag every match of a target whose sources speak different currencies."""

    found: dict[int, str] = {}
    for index, source in enumerate(entry.sources):
        if source.status != "auto" or source.column is None:
            continue
        profile = columns.get((source.file, source.column))
        currency = _currency_of(source.column, profile.samples if profile else ())
        if currency is not None:
            found[index] = currency

    currencies = sorted(set(found.values()))
    if len(currencies) < 2:
        return {}
    listed = " ve ".join(currencies)
    return {
        index: (
            f"'{entry.target_column}' sütunu farklı para birimlerinden besleniyor ({listed}); "
            f"bu kaynak {currency}. Dönüştürmeden birleştirmek değerleri karşılaştırılamaz kılar."
        )
        for index, currency in found.items()
    }


def _currency_of(column_name: str, samples: Iterable[object]) -> str | None:
    """Read a currency from the column name, then from its sample values."""

    for token in _tokens(column_name):
        if token in CURRENCY_WORDS:
            return CURRENCY_WORDS[token]
    for symbol, name in CURRENCY_SYMBOLS.items():
        if symbol in column_name:
            return name
    for value in samples:
        text = str(value)
        for symbol, name in CURRENCY_SYMBOLS.items():
            if symbol in text:
                return name
        for token in _tokens(text):
            if token in CURRENCY_WORDS:
                return CURRENCY_WORDS[token]
    return None


def _demote(source: SourceMatch, warning: str, profile: ColumnProfile | None) -> SourceMatch:
    """Send one match to review, keeping what the model said after the warning."""

    reason = f"{warning} Öneri: {source.reason}" if source.reason else warning
    samples = list(source.samples) if source.samples else []
    if not samples and profile is not None:
        samples = list(profile.samples[:MAX_REVIEW_SAMPLES])
    return SourceMatch(
        file=source.file,
        column=source.column,
        confidence=source.confidence,
        status="review",
        reason=reason,
        samples=samples,
    )


def _columns_by_file(profiles: Sequence[FileProfile]) -> dict[tuple[str, str], ColumnProfile]:
    lookup: dict[tuple[str, str], ColumnProfile] = {}
    for profile in profiles:
        name = profile.path.name
        for table in profile.tables:
            for column in table.columns:
                lookup.setdefault((name, column.name), column)
    return lookup


def _tokens(text: str) -> frozenset[str]:
    """Lower-case, Turkish-aware word tokens of a name or a value."""

    folded = text.translate(_FOLD).lower()
    return frozenset(part for part in _TOKEN.split(folded) if part)
