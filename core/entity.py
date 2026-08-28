"""Entity resolution: normalization, blocking, embedding, and the grey zone.

Entity resolution (spec §4, §7) has four layers, cheapest first, and this
module implements all of them.  Layers 1-3 are decided by code alone; the LLM
is reached only in layer 4, for the pairs that sit between the two thresholds
(spec §14).

Layer 1 — :func:`normalize` produces a comparison key for a value:
Turkish-aware lowercasing, diacritic folding, number canonicalisation, unit
conversion (``33cl`` -> ``330ml``), punctuation removal, and abbreviation
expansion.  The key exists *only for comparison*: source records are never
rewritten, so provenance stays intact.

Layer 2 — :func:`make_blocks` groups records that are worth comparing at all.
Comparing every pair is quadratic and therefore forbidden here; candidates come
from :func:`candidate_pairs`, which never leaves a block.

Layer 3 — :func:`score_pairs` embeds the comparison keys of blocked pairs and
scores them with cosine similarity.  Two thresholds split the result: at or
above ``high`` the pair is the same product, below ``low`` it is a different
one, and both verdicts are reached without an LLM.

Layer 4 — :func:`review_grey_zone` sends what is left, the band between the
thresholds, to the LLM one pair at a time.  That band is meant to stay a small
fraction of all pairs (:func:`grey_zone_ratio` measures it), which is what
keeps the cost bounded as record count grows.  The LLM is **advisory only**: a
grey pair keeps ``status="review"`` whatever the answer, so it reaches a human
in the cluster approval step and never merges on its own.  A malformed,
low-confidence, or failed answer leaves the pair ``"undecided"`` — it is never
quietly read as "same".

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
import json
import math
import re
from typing import Any, Iterable, Iterator, Mapping, Sequence

from core.llm import EmbeddingClient, LLMClient


class EntityError(ValueError):
    """Raised for an unusable blocking request or record."""


#: Block key used for records whose blocking value normalises to nothing.
#: Alphanumeric keys cannot collide with it.
UNBLOCKED_KEY = "<unblocked>"

#: Default number of leading characters used by the ``prefix`` strategy.
DEFAULT_PREFIX_LENGTH = 3

#: Blocking strategies accepted by :func:`make_blocks`.
BLOCKING_STRATEGIES = ("prefix", "brand", "category")

#: Similarity at or above which a pair is the same product without an LLM.
DEFAULT_HIGH_THRESHOLD = 0.85

#: Similarity below which a pair is a different product without an LLM.
DEFAULT_LOW_THRESHOLD = 0.60

#: Least confidence an LLM suggestion needs before it is recorded at all.
DEFAULT_LLM_MIN_CONFIDENCE = 0.5

#: Verdict for a pair.  ``"undecided"`` means no layer could answer safely.
DECISION_SAME = "same"
DECISION_DIFFERENT = "different"
DECISION_UNDECIDED = "undecided"

#: Which layer produced the verdict.
SOURCE_EMBEDDING = "embedding"
SOURCE_LLM = "llm"
SOURCE_NONE = "none"

_GREY_SYSTEM_PROMPT = """You judge whether two product descriptions refer to the same real-world product.
Return only JSON: {"same": true, "confidence": 0.0, "reason": "..."}.
"same" must be a boolean and "confidence" a number between 0 and 1.
Judge only the two supplied descriptions; do not invent attributes, do not request
more data, and do not return anything but that JSON object. Your answer is advisory:
a human confirms every merge, so answer "same": false when you are not convinced."""

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


@dataclass(frozen=True)
class SimilarityThresholds:
    """The two cut-offs that define the grey zone, plus the LLM trust floor.

    ``high`` and ``low`` bound the band that is escalated: ``similarity >=
    high`` is decided as the same product and ``similarity < low`` as a
    different one, both without an LLM.  Widening the band buys accuracy with
    LLM calls; narrowing it does the reverse.  ``llm_min_confidence`` is the
    least confidence a suggestion needs before it is recorded — under it the
    pair stays undecided.
    """

    high: float = DEFAULT_HIGH_THRESHOLD
    low: float = DEFAULT_LOW_THRESHOLD
    llm_min_confidence: float = DEFAULT_LLM_MIN_CONFIDENCE

    def __post_init__(self) -> None:
        for name in ("high", "low", "llm_min_confidence"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise EntityError(f"{name} must be between 0 and 1")
        if self.low > self.high:
            raise EntityError("low threshold cannot exceed high threshold")


DEFAULT_THRESHOLDS = SimilarityThresholds()


@dataclass(frozen=True)
class PairDecision:
    """One candidate pair and how far the layers got with it.

    ``status`` is ``"auto"`` only when code alone settled the pair; every grey
    pair stays ``"review"`` so the user confirms it later.  ``grey`` records
    that the similarity fell in the band, which stays true after the LLM
    answers — it describes how the pair was routed, not whether it is resolved.
    """

    left: BlockedRecord
    right: BlockedRecord
    similarity: float
    decision: str
    status: str
    source: str
    reason: str
    grey: bool = False
    llm_confidence: float | None = None

    @property
    def block_key(self) -> str:
        return self.left.block_key


def score_pairs(
    pairs: Iterable[tuple[BlockedRecord, BlockedRecord]],
    embedder: EmbeddingClient,
    *,
    thresholds: SimilarityThresholds | None = None,
) -> list[PairDecision]:
    """Layer 3: score blocked pairs by embedding similarity, no LLM involved.

    Every distinct comparison key is embedded once, in a single
    :meth:`~core.llm.EmbeddingClient.embed` call, so cost tracks distinct keys
    rather than pair count.  Similarity is cosine, clamped to ``[0, 1]``: an
    opposing vector is as different as an orthogonal one for our purposes.

    Pairs whose similarity lands in the grey band come back ``"undecided"`` and
    ``grey=True``, ready for :func:`review_grey_zone`.  A pair whose key
    normalised to nothing is never guessed at — it comes back undecided too.
    """

    settings = thresholds or DEFAULT_THRESHOLDS
    candidates = list(pairs)
    vectors = _embed_keys(candidates, embedder)

    decisions: list[PairDecision] = []
    for left, right in candidates:
        if not left.normalized or not right.normalized:
            decisions.append(
                _undecided(left, right, 0.0, SOURCE_NONE, "Karşılaştırma anahtarı boş; el ile incelenmeli.")
            )
            continue
        similarity = _cosine(vectors[left.normalized], vectors[right.normalized])
        decisions.append(_classify(left, right, similarity, settings))
    return decisions


def review_grey_zone(
    decisions: Iterable[PairDecision],
    llm: LLMClient,
    *,
    thresholds: SimilarityThresholds | None = None,
) -> list[PairDecision]:
    """Layer 4: ask the LLM about the grey band only, one pair per call.

    Pairs already settled by layer 3 are passed through untouched, so the
    number of requests equals the number of grey pairs — see
    :func:`grey_zone_ratio`.  Only the two compared values and their normalised
    keys are sent; the surrounding record and its other columns never leave.

    The answer is a suggestion: the pair keeps ``status="review"`` either way.
    Anything unusable — invalid JSON, a missing or non-boolean ``same``, a
    confidence below ``llm_min_confidence``, or a provider failure — leaves the
    pair ``"undecided"`` rather than merged.
    """

    settings = thresholds or DEFAULT_THRESHOLDS
    reviewed: list[PairDecision] = []
    for decision in decisions:
        if not decision.grey or decision.source == SOURCE_LLM:
            reviewed.append(decision)
            continue
        reviewed.append(_ask_llm(decision, llm, settings))
    return reviewed


def resolve_pairs(
    blocks: Mapping[str, Sequence[BlockedRecord]],
    *,
    embedder: EmbeddingClient,
    llm: LLMClient | None = None,
    thresholds: SimilarityThresholds | None = None,
    include_unblocked: bool = True,
) -> list[PairDecision]:
    """Run layers 3 and 4 over the blocks produced by :func:`make_blocks`.

    Without ``llm`` the grey band is simply left undecided for the user.
    """

    settings = thresholds or DEFAULT_THRESHOLDS
    decisions = score_pairs(
        candidate_pairs(blocks, include_unblocked=include_unblocked),
        embedder,
        thresholds=settings,
    )
    if llm is None:
        return decisions
    return review_grey_zone(decisions, llm, thresholds=settings)


def grey_pairs(decisions: Iterable[PairDecision]) -> list[PairDecision]:
    """The pairs that fell in the band — the only ones an LLM ever sees."""

    return [decision for decision in decisions if decision.grey]


def grey_zone_ratio(decisions: Sequence[PairDecision]) -> float:
    """Share of pairs that need an LLM call, ``0.0`` when there are no pairs.

    The spec budgets roughly 1-5%; a materially larger share means the
    thresholds or the blocking strategy need tightening before scaling up.
    """

    if not decisions:
        return 0.0
    return len(grey_pairs(decisions)) / len(decisions)


def pending_review(decisions: Iterable[PairDecision]) -> list[PairDecision]:
    """Pairs a human still has to confirm; ``apply`` must not merge these."""

    return [decision for decision in decisions if decision.status == "review"]


def _classify(
    left: BlockedRecord,
    right: BlockedRecord,
    similarity: float,
    thresholds: SimilarityThresholds,
) -> PairDecision:
    if similarity >= thresholds.high:
        return PairDecision(
            left=left,
            right=right,
            similarity=similarity,
            decision=DECISION_SAME,
            status="auto",
            source=SOURCE_EMBEDDING,
            reason=f"Benzerlik {similarity:.2f} >= {thresholds.high:.2f} (yüksek eşik).",
        )
    if similarity < thresholds.low:
        return PairDecision(
            left=left,
            right=right,
            similarity=similarity,
            decision=DECISION_DIFFERENT,
            status="auto",
            source=SOURCE_EMBEDDING,
            reason=f"Benzerlik {similarity:.2f} < {thresholds.low:.2f} (düşük eşik).",
        )
    return PairDecision(
        left=left,
        right=right,
        similarity=similarity,
        decision=DECISION_UNDECIDED,
        status="review",
        source=SOURCE_EMBEDDING,
        reason=(
            f"Benzerlik {similarity:.2f}, gri bölgede "
            f"[{thresholds.low:.2f}, {thresholds.high:.2f}); LLM'e sorulacak."
        ),
        grey=True,
    )


def _undecided(
    left: BlockedRecord,
    right: BlockedRecord,
    similarity: float,
    source: str,
    reason: str,
    *,
    grey: bool = False,
    llm_confidence: float | None = None,
) -> PairDecision:
    return PairDecision(
        left=left,
        right=right,
        similarity=similarity,
        decision=DECISION_UNDECIDED,
        status="review",
        source=source,
        reason=reason,
        grey=grey,
        llm_confidence=llm_confidence,
    )


def _embed_keys(
    pairs: Sequence[tuple[BlockedRecord, BlockedRecord]], embedder: EmbeddingClient
) -> dict[str, list[float]]:
    """Embed each distinct non-empty comparison key exactly once."""

    keys: list[str] = []
    seen: set[str] = set()
    for left, right in pairs:
        for record in (left, right):
            if record.normalized and record.normalized not in seen:
                seen.add(record.normalized)
                keys.append(record.normalized)
    if not keys:
        return {}

    vectors = list(embedder.embed(keys))
    if len(vectors) != len(keys):
        raise EntityError(
            f"Embedding sağlayıcısı {len(keys)} anahtar için {len(vectors)} vektör döndürdü."
        )
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) > 1 or dimensions == {0}:
        raise EntityError("Embedding vektörleri boş ya da farklı boyutlarda.")
    return dict(zip(keys, ([float(value) for value in vector] for vector in vectors)))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity clamped to ``[0, 1]``; a zero vector scores 0."""

    dot = sum(a * b for a, b in zip(left, right))
    magnitude = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    if magnitude == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / magnitude))


def _ask_llm(
    decision: PairDecision, llm: LLMClient, thresholds: SimilarityThresholds
) -> PairDecision:
    try:
        response = llm.complete(_GREY_SYSTEM_PROMPT, _grey_user_prompt(decision))
    except Exception as error:  # noqa: BLE001 - one bad pair must not stop the batch
        return _undecided(
            decision.left,
            decision.right,
            decision.similarity,
            SOURCE_LLM,
            f"LLM çağrısı başarısız: {error}. Çift incelenecek olarak kaldı.",
            grey=True,
        )

    suggestion, error_message = _parse_suggestion(response, thresholds)
    if suggestion is None:
        return _undecided(
            decision.left,
            decision.right,
            decision.similarity,
            SOURCE_LLM,
            f"{error_message} Çift incelenecek olarak kaldı.",
            grey=True,
        )
    verdict = DECISION_SAME if suggestion["same"] else DECISION_DIFFERENT
    return PairDecision(
        left=decision.left,
        right=decision.right,
        similarity=decision.similarity,
        decision=verdict,
        # Advisory only: the user confirms grey pairs in the cluster review.
        status="review",
        source=SOURCE_LLM,
        reason=f"LLM önerisi ({verdict}): {suggestion['reason']}",
        grey=True,
        llm_confidence=suggestion["confidence"],
    )


def _grey_user_prompt(decision: PairDecision) -> str:
    """Serialize the two compared values only — never the whole record."""

    document = {
        "left": {"value": str(decision.left.value), "normalized": decision.left.normalized},
        "right": {"value": str(decision.right.value), "normalized": decision.right.normalized},
        "embedding_similarity": round(decision.similarity, 4),
    }
    return json.dumps(document, ensure_ascii=False)


def _parse_suggestion(
    response: str, thresholds: SimilarityThresholds
) -> tuple[dict[str, Any] | None, str]:
    """Parse a grey-zone answer without trusting its shape or its confidence."""

    try:
        document = json.loads(_strip_json_fence(response))
    except (TypeError, json.JSONDecodeError):
        return None, "LLM yanıtı geçerli JSON değil."
    if not isinstance(document, dict):
        return None, "LLM yanıtı bir JSON nesnesi değil."

    same = document.get("same")
    confidence = document.get("confidence")
    reason = document.get("reason")
    if not isinstance(same, bool):
        return None, "LLM yanıtında 'same' alanı boolean değil."
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None, "LLM yanıtında 'confidence' sayı değil."
    if not 0.0 <= float(confidence) <= 1.0:
        return None, "LLM güven değeri 0-1 aralığında değil."
    if not isinstance(reason, str) or not reason.strip():
        return None, "LLM yanıtında gerekçe yok."
    if float(confidence) < thresholds.llm_min_confidence:
        return None, (
            f"LLM güveni {float(confidence):.2f} < {thresholds.llm_min_confidence:.2f}."
        )
    return {"same": same, "confidence": float(confidence), "reason": reason.strip()}, ""


def _strip_json_fence(response: str) -> str:
    text = response.strip() if isinstance(response, str) else ""
    if text.startswith("```") and text.endswith("```"):
        return text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return text


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
