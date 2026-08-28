"""Layer 3 of entity resolution: embedding similarity and the two thresholds.

Every embedder here is a fake, so no test makes a network request.
"""

from __future__ import annotations

import copy
import math

import pytest

from core.entity import (
    SimilarityThresholds,
    EntityError,
    candidate_pairs,
    grey_zone_ratio,
    make_blocks,
    resolve_pairs,
    score_pairs,
)
from core.llm import FakeEmbeddingClient


REFERENCE = [1.0, 0.0]


def at_similarity(value: float) -> list[float]:
    """A unit vector whose cosine similarity with :data:`REFERENCE` is ``value``."""

    return [value, math.sqrt(max(0.0, 1.0 - value * value))]


def score(names: list[str], vectors: dict[str, list[float]], **kwargs) -> list:
    records = [{"name": name} for name in names]
    blocks = make_blocks(records)
    embedder = FakeEmbeddingClient(vectors=vectors)
    return score_pairs(candidate_pairs(blocks), embedder, **kwargs)


def test_high_similarity_is_decided_same_without_an_llm() -> None:
    decisions = score(
        ["Coca Cola 330ml", "Coca-Cola Kutu 33 cl"],
        {"coca cola 330ml": REFERENCE, "coca cola kutu 330ml": at_similarity(0.93)},
    )

    (pair,) = decisions
    assert pair.similarity == pytest.approx(0.93)
    assert pair.decision == "same"
    assert pair.status == "auto"
    assert pair.source == "embedding"
    assert pair.grey is False
    assert "0.85" in pair.reason


def test_low_similarity_is_decided_different_without_an_llm() -> None:
    decisions = score(
        ["Coca Cola 330ml", "Coca Cola Zero 330ml"],
        {"coca cola 330ml": REFERENCE, "coca cola zero 330ml": at_similarity(0.20)},
    )

    (pair,) = decisions
    assert pair.similarity == pytest.approx(0.20)
    assert pair.decision == "different"
    assert pair.status == "auto"
    assert pair.source == "embedding"
    assert pair.grey is False


def test_similarity_between_the_thresholds_lands_in_the_grey_zone() -> None:
    decisions = score(
        ["Coca Cola 330ml", "Coca Cola Zero 330ml"],
        {"coca cola 330ml": REFERENCE, "coca cola zero 330ml": at_similarity(0.72)},
    )

    (pair,) = decisions
    assert pair.similarity == pytest.approx(0.72)
    assert pair.grey is True
    # Layer 3 never guesses inside the band; the pair waits for the LLM.
    assert pair.decision == "undecided"
    assert pair.status == "review"
    assert grey_zone_ratio(decisions) == 1.0


@pytest.mark.parametrize(
    ("thresholds", "expected"),
    [
        (SimilarityThresholds(high=0.70, low=0.40), "same"),
        (SimilarityThresholds(high=0.95, low=0.80), "different"),
        (SimilarityThresholds(high=0.95, low=0.40), "undecided"),
    ],
)
def test_thresholds_move_the_boundaries(thresholds, expected) -> None:
    decisions = score(
        ["Coca Cola 330ml", "Coca Cola Zero 330ml"],
        {"coca cola 330ml": REFERENCE, "coca cola zero 330ml": at_similarity(0.72)},
        thresholds=thresholds,
    )

    assert decisions[0].decision == expected


def test_a_similarity_exactly_on_the_high_threshold_is_the_same_product() -> None:
    # [3, 4] against [1, 0] is exactly 3/5, so the boundary is hit without
    # floating point slack.
    decisions = score(
        ["Coca Cola 330ml", "Coca Cola Zero 330ml"],
        {"coca cola 330ml": REFERENCE, "coca cola zero 330ml": [3.0, 4.0]},
        thresholds=SimilarityThresholds(high=0.60, low=0.30),
    )

    assert decisions[0].similarity == 0.6
    assert decisions[0].decision == "same"
    assert decisions[0].status == "auto"


def test_a_similarity_exactly_on_the_low_threshold_is_grey_not_different() -> None:
    decisions = score(
        ["Coca Cola 330ml", "Coca Cola Zero 330ml"],
        {"coca cola 330ml": REFERENCE, "coca cola zero 330ml": [3.0, 4.0]},
        thresholds=SimilarityThresholds(high=0.90, low=0.60),
    )

    assert decisions[0].similarity == 0.6
    assert decisions[0].grey is True


def test_each_distinct_key_is_embedded_once_in_a_single_call() -> None:
    # Three records, two of which share a comparison key -> two keys, three pairs.
    records = [
        {"name": "Coca Cola 330ml"},
        {"name": "COCA COLA 0,33 LT"},
        {"name": "Coca Cola Zero 330ml"},
    ]
    embedder = FakeEmbeddingClient(
        vectors={"coca cola 330ml": REFERENCE, "coca cola zero 330ml": at_similarity(0.5)}
    )

    decisions = score_pairs(candidate_pairs(make_blocks(records)), embedder)

    assert len(decisions) == 3
    assert len(embedder.calls) == 1
    assert embedder.calls[0] == ["coca cola 330ml", "coca cola zero 330ml"]


def test_opposing_vectors_are_clamped_and_count_as_different() -> None:
    decisions = score(
        ["Coca Cola 330ml", "Coca Cola Zero 330ml"],
        {"coca cola 330ml": REFERENCE, "coca cola zero 330ml": [-1.0, 0.0]},
    )

    assert decisions[0].similarity == 0.0
    assert decisions[0].decision == "different"


def test_a_zero_vector_scores_zero_instead_of_dividing_by_zero() -> None:
    decisions = score(
        ["Coca Cola 330ml", "Coca Cola Zero 330ml"],
        {"coca cola 330ml": REFERENCE, "coca cola zero 330ml": [0.0, 0.0]},
    )

    assert decisions[0].similarity == 0.0
    assert decisions[0].decision == "different"


def test_an_empty_comparison_key_is_never_guessed_at() -> None:
    records = [{"name": "!!!"}, {"name": "  -  "}]
    embedder = FakeEmbeddingClient()

    decisions = score_pairs(candidate_pairs(make_blocks(records)), embedder)

    (pair,) = decisions
    assert pair.decision == "undecided"
    assert pair.status == "review"
    assert pair.grey is False  # not the LLM's problem either: there is nothing to compare
    assert "boş" in pair.reason
    assert embedder.calls == []  # nothing was worth embedding


@pytest.mark.parametrize(
    "vectors",
    [
        [[1.0, 0.0]],  # fewer vectors than keys
        [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]],  # more vectors than keys
    ],
)
def test_a_provider_returning_the_wrong_number_of_vectors_is_rejected(vectors) -> None:
    class MiscountingEmbedder:
        def embed(self, texts):
            return vectors

    with pytest.raises(EntityError, match="vektör"):
        score_pairs(
            candidate_pairs(make_blocks([{"name": "Coca Cola 330ml"}, {"name": "Coca Cola Zero"}])),
            MiscountingEmbedder(),
        )


@pytest.mark.parametrize("vectors", [[[1.0, 0.0], [1.0]], [[], []]])
def test_ragged_or_empty_vectors_are_rejected(vectors) -> None:
    class RaggedEmbedder:
        def embed(self, texts):
            return vectors

    with pytest.raises(EntityError, match="boyut|boş"):
        score_pairs(
            candidate_pairs(make_blocks([{"name": "Coca Cola 330ml"}, {"name": "Coca Cola Zero"}])),
            RaggedEmbedder(),
        )


def test_invalid_thresholds_are_rejected() -> None:
    with pytest.raises(EntityError, match="low threshold cannot exceed"):
        SimilarityThresholds(high=0.4, low=0.9)
    with pytest.raises(EntityError, match="high must be between"):
        SimilarityThresholds(high=1.5)
    with pytest.raises(EntityError, match="llm_min_confidence must be between"):
        SimilarityThresholds(llm_min_confidence=-0.1)


def test_scoring_leaves_the_source_records_untouched() -> None:
    records = [{"name": "Coca Cola 330ml", "id": "1"}, {"name": "Coca-Cola Kutu 33 cl", "id": "2"}]
    snapshot = copy.deepcopy(records)
    blocks = make_blocks(records)

    (pair,) = score_pairs(candidate_pairs(blocks), FakeEmbeddingClient())

    assert records == snapshot
    assert pair.left.record is records[0]
    assert pair.right.record is records[1]
    assert pair.block_key == pair.left.block_key == pair.right.block_key


def test_resolve_pairs_without_an_llm_leaves_the_grey_zone_undecided() -> None:
    records = [{"name": "Coca Cola 330ml"}, {"name": "Coca Cola Zero 330ml"}]
    embedder = FakeEmbeddingClient(
        vectors={"coca cola 330ml": REFERENCE, "coca cola zero 330ml": at_similarity(0.70)}
    )

    decisions = resolve_pairs(make_blocks(records), embedder=embedder)

    assert [decision.decision for decision in decisions] == ["undecided"]
    assert decisions[0].source == "embedding"
    assert decisions[0].grey is True


def test_grey_zone_ratio_is_zero_without_pairs() -> None:
    assert grey_zone_ratio([]) == 0.0
