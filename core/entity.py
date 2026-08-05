"""Entity resolution layers 1-2: deterministic normalization and blocking.

Entity resolution (spec §4, §7) has four layers.  This module implements the
first two, and both are **pure code — no LLM is called here** (spec §14).  The
LLM only sees the grey zone in a later layer.

Layer 1 — :func:`normalize` produces a comparison key for a value:
Turkish-aware lowercasing, diacritic folding, number canonicalisation, unit
conversion (``33cl`` -> ``330ml``), punctuation removal, and abbreviation
expansion.  The key exists *only for comparison*: source records are never
rewritten, so provenance stays intact.

Layer 2 — :func:`make_blocks` groups records that are worth comparing at all.
Comparing every pair is quadratic and therefore forbidden here; candidates come
from :func:`candidate_pairs`, which never leaves a block.

Documented defaults
-------------------
Units (``DEFAULT_UNITS``) convert to a base unit per dimension: volume to
``ml`` (``cc``/``ml`` 1, ``cl`` 10, ``dl`` 100, ``l``/``lt``/``litre`` 1000)
and mass to ``g`` (``mg`` 0.001, ``g``/``gr``/``gram`` 1,
``kg``/``kilo``/``kilogram`` 1000).  Abbreviations (``DEFAULT_ABBREVIATIONS``)
expand common Turkish retail short forms such as ``adt`` -> ``adet``.  Both
tables are replaceable through :class:`NormalizationConfig`.

Numbers follow the same convention as :mod:`core.normalize`: a lone ``,`` is a
decimal separator (``0,036`` -> ``0.036``), a lone ``.`` is a decimal point, so
the ambiguous ``1.500`` reads as ``1.5``.  Only unambiguous grouped forms are
ungrouped: those with a decimal part (``1.500,25`` -> ``1500.25``) and those
with two or more groups (``1.234.567`` -> ``1234567``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
from functools import lru_cache
from itertools import combinations
import re
from typing import Iterable, Iterator, Mapping, Sequence


class EntityError(ValueError):
    """Raised for an unusable blocking request or record."""


#: Block key used for records whose blocking value normalises to nothing.
#: Alphanumeric keys cannot collide with it.
UNBLOCKED_KEY = "<unblocked>"

#: Default number of leading characters used by the ``prefix`` strategy.
DEFAULT_PREFIX_LENGTH = 3

#: Blocking strategies accepted by :func:`make_blocks`.
BLOCKING_STRATEGIES = ("prefix", "brand", "category")

#: Unit token -> (factor, base unit).  See the module docstring.
DEFAULT_UNITS: dict[str, tuple[Decimal, str]] = {
    "ml": (Decimal(1), "ml"),
    "cc": (Decimal(1), "ml"),
    "cl": (Decimal(10), "ml"),
    "dl": (Decimal(100), "ml"),
    "l": (Decimal(1000), "ml"),
    "lt": (Decimal(1000), "ml"),
    "litre": (Decimal(1000), "ml"),
    "mg": (Decimal("0.001"), "g"),
    "g": (Decimal(1), "g"),
    "gr": (Decimal(1), "g"),
    "gram": (Decimal(1), "g"),
    "kg": (Decimal(1000), "g"),
    "kilo": (Decimal(1000), "g"),
    "kilogram": (Decimal(1000), "g"),
}

#: Short form -> long form, applied token by token after punctuation removal.
#: Keys are written in already-normalised (folded, lowercase) form.
DEFAULT_ABBREVIATIONS: dict[str, str] = {
    "ad": "adet",
    "adt": "adet",
    "pk": "paket",
    "pkt": "paket",
    "kt": "kutu",
    "ktu": "kutu",
    "sse": "sise",
    "tnk": "teneke",
    "byk": "buyuk",
    "kck": "kucuk",
    "orj": "orijinal",
}

# "İ" and "I" do not lowercase to "i"/"ı" without this map, so Turkish text is
# folded before ``str.lower`` runs.
_TURKISH_LOWER = str.maketrans({"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"})
_DIACRITIC_FOLD = str.maketrans(
    {
        "ı": "i",
        "ş": "s",
        "ğ": "g",
        "ü": "u",
        "ö": "o",
        "ç": "c",
        "â": "a",
        "î": "i",
        "û": "u",
        "é": "e",
    }
)

_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_PLAIN = re.compile(r"^\d+(?:\.\d+)?$")
_TR_GROUPED_DECIMAL = re.compile(r"^\d{1,3}(?:\.\d{3})+,\d+$")
_EN_GROUPED_DECIMAL = re.compile(r"^\d{1,3}(?:,\d{3})+\.\d+$")
_TR_GROUPED_INTEGER = re.compile(r"^\d{1,3}(?:\.\d{3}){2,}$")
_EN_GROUPED_INTEGER = re.compile(r"^\d{1,3}(?:,\d{3}){2,}$")
_TR_DECIMAL = re.compile(r"^\d+,\d+$")
# Sentinel that survives punctuation stripping so decimal points are kept.
_DECIMAL_POINT = "\x00"


@dataclass(frozen=True)
class NormalizationConfig:
    """Replaceable conversion tables for :func:`normalize`.

    ``units`` maps a unit token to ``(factor, base_unit)``; ``abbreviations``
    maps a normalised token to its expansion.
    """

    units: Mapping[str, tuple[Decimal, str]] = field(default_factory=lambda: dict(DEFAULT_UNITS))
    abbreviations: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_ABBREVIATIONS))


DEFAULT_CONFIG = NormalizationConfig()


@dataclass(frozen=True)
class BlockedRecord:
    """One record placed in a block, next to its untouched original.

    ``record`` and ``value`` are the caller's objects: nothing is rewritten.
    ``normalized`` is the comparison key produced by :func:`normalize`.
    """

    index: int
    record: object
    value: object
    normalized: str
    block_key: str


def normalize(value: object, *, config: NormalizationConfig | None = None) -> str:
    """Return the deterministic comparison key for ``value``.

    The result is lowercase ASCII words separated by single spaces, with units
    converted to their base unit (``0,33 lt`` and ``33cl`` both become
    ``330ml``).  Missing or blank values return ``""``.  The input is never
    modified — this key is used for comparison only.
    """

    settings = config or DEFAULT_CONFIG
    if value is None:
        return ""
    text = str(value)
    if not text.strip():
        return ""
    text = text.translate(_TURKISH_LOWER).lower().translate(_DIACRITIC_FOLD)
    text = _canonical_numbers(text)
    text = _convert_units(text, settings.units)
    text = _strip_punctuation(text)
    expansions = settings.abbreviations
    return " ".join(expansions.get(token, token) for token in text.split())


def make_blocks(
    records: Iterable[object],
    *,
    strategy: str | Sequence[str] = "prefix",
    value_field: str = "name",
    brand_field: str = "brand",
    category_field: str = "category",
    prefix_length: int = DEFAULT_PREFIX_LENGTH,
    config: NormalizationConfig | None = None,
) -> dict[str, list[BlockedRecord]]:
    """Group records into blocks so only same-block pairs are ever compared.

    ``records`` may be mappings (``{"name": ..., "brand": ...}``), plain
    strings, or objects with attributes.  ``strategy`` is one of
    ``"prefix"`` (first ``prefix_length`` characters of the normalised value),
    ``"brand"``, or ``"category"``; a sequence of them builds a composite key
    joined with ``"|"``.  Each record lands in exactly one block, so blocks
    stay disjoint and candidate pairs are never generated twice.

    The returned :class:`BlockedRecord` values keep the original record intact.
    Records whose key normalises to nothing land in :data:`UNBLOCKED_KEY`.
    """

    strategies = _validate_strategies(strategy)
    if prefix_length < 1:
        raise EntityError("prefix_length must be at least 1")
    settings = config or DEFAULT_CONFIG

    blocks: dict[str, list[BlockedRecord]] = {}
    for index, record in enumerate(records):
        value = _record_field(record, value_field, value_field)
        normalized = normalize(value, config=settings)
        parts = [
            _block_part(
                name,
                record,
                normalized,
                brand_field=brand_field,
                category_field=category_field,
                prefix_length=prefix_length,
                config=settings,
            )
            for name in strategies
        ]
        key = UNBLOCKED_KEY if not all(parts) else "|".join(parts)
        blocks.setdefault(key, []).append(
            BlockedRecord(
                index=index,
                record=record,
                value=value,
                normalized=normalized,
                block_key=key,
            )
        )
    return blocks


def candidate_pairs(
    blocks: Mapping[str, Sequence[BlockedRecord]],
    *,
    include_unblocked: bool = True,
) -> Iterator[tuple[BlockedRecord, BlockedRecord]]:
    """Yield the pairs worth comparing: within a block, never across blocks.

    This is the only pair source in this module; an all-pairs sweep is never
    performed.  Set ``include_unblocked`` to ``False`` to skip records that had
    no usable blocking key instead of comparing them with each other.
    """

    for key, members in blocks.items():
        if not include_unblocked and key == UNBLOCKED_KEY:
            continue
        yield from combinations(members, 2)


def pair_count(
    blocks: Mapping[str, Sequence[BlockedRecord]],
    *,
    include_unblocked: bool = True,
) -> int:
    """Number of pairs :func:`candidate_pairs` would yield, counted in O(blocks)."""

    total = 0
    for key, members in blocks.items():
        if not include_unblocked and key == UNBLOCKED_KEY:
            continue
        size = len(members)
        total += size * (size - 1) // 2
    return total


def all_pairs_count(record_count: int) -> int:
    """Pairs a naive all-pairs comparison would need; for reporting only."""

    return record_count * (record_count - 1) // 2


def _validate_strategies(strategy: str | Sequence[str]) -> tuple[str, ...]:
    names = (strategy,) if isinstance(strategy, str) else tuple(strategy)
    if not names:
        raise EntityError("At least one blocking strategy is required")
    unknown = [name for name in names if name not in BLOCKING_STRATEGIES]
    if unknown:
        raise EntityError(
            f"Unknown blocking strategy: {', '.join(unknown)}. "
            f"Supported: {', '.join(BLOCKING_STRATEGIES)}"
        )
    return names


def _block_part(
    strategy: str,
    record: object,
    normalized: str,
    *,
    brand_field: str,
    category_field: str,
    prefix_length: int,
    config: NormalizationConfig,
) -> str:
    if strategy == "prefix":
        return normalized.replace(" ", "")[:prefix_length]
    if strategy == "brand":
        brand = normalize(_record_field(record, brand_field, "brand"), config=config)
        # Falling back to the leading token keeps brand blocking usable for
        # sources that only ship a product name.
        return brand or normalized.split(" ")[0]
    category = normalize(_record_field(record, category_field, "category"), config=config)
    return category


def _record_field(record: object, field_name: str, role: str) -> object:
    """Read one field from a mapping, a bare string, or an object."""

    if isinstance(record, Mapping):
        if field_name not in record:
            raise EntityError(f"Record {record!r} has no '{field_name}' field required for {role}")
        return record[field_name]
    if isinstance(record, str):
        return record
    if not hasattr(record, field_name):
        raise EntityError(f"Record {record!r} has no '{field_name}' attribute required for {role}")
    return getattr(record, field_name)


def _canonical_numbers(text: str) -> str:
    """Rewrite grouped and comma-decimal numbers to plain ``123.45`` form."""

    return _NUMBER.sub(lambda match: _canonical_number(match.group(0)), text)


def _canonical_number(token: str) -> str:
    # Precedence matches :mod:`core.normalize`: a lone dot is always a decimal
    # point, so the ambiguous "1.500" reads as 1.5 rather than 1500.
    if _PLAIN.fullmatch(token):
        return token
    if _TR_GROUPED_DECIMAL.fullmatch(token):
        return token.replace(".", "").replace(",", ".")
    if _EN_GROUPED_DECIMAL.fullmatch(token):
        return token.replace(",", "")
    if _TR_GROUPED_INTEGER.fullmatch(token):
        return token.replace(".", "")
    if _EN_GROUPED_INTEGER.fullmatch(token):
        return token.replace(",", "")
    if _TR_DECIMAL.fullmatch(token):
        return token.replace(",", ".")
    return token


def _convert_units(text: str, units: Mapping[str, tuple[Decimal, str]]) -> str:
    if not units:
        return text
    pattern = _unit_pattern(tuple(sorted(units)))

    def replace(match: re.Match[str]) -> str:
        factor, base = units[match.group(2)]
        try:
            amount = Decimal(match.group(1)) * Decimal(factor)
        except DecimalException:
            return match.group(0)
        return f"{_format_quantity(amount)}{base}"

    return pattern.sub(replace, text)


@lru_cache(maxsize=16)
def _unit_pattern(unit_names: tuple[str, ...]) -> re.Pattern[str]:
    # Longest first so "kg" is not matched as "g", and the lookarounds keep the
    # match off a neighbouring number ("1.5") or word ("3lu").
    alternatives = "|".join(re.escape(name) for name in sorted(unit_names, key=len, reverse=True))
    return re.compile(rf"(?<![\d.])(\d+(?:\.\d+)?)\s*({alternatives})(?![a-z0-9])")


def _format_quantity(amount: Decimal) -> str:
    """Render a quantity without exponent or trailing-zero noise."""

    try:
        if amount == amount.to_integral_value():
            return str(amount.quantize(Decimal(1)))
        return format(amount.normalize(), "f")
    except DecimalException:
        return format(amount, "f")


def _strip_punctuation(text: str) -> str:
    """Drop every non-alphanumeric character, keeping decimal points."""

    protected = re.sub(r"(?<=\d)\.(?=\d)", _DECIMAL_POINT, text)
    cleaned = re.sub(rf"[^0-9a-z{_DECIMAL_POINT}]+", " ", protected)
    return cleaned.replace(_DECIMAL_POINT, ".")
