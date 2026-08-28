"""Layer 4 of entity resolution: the grey zone, and only the grey zone.

The LLM here is a fake and so is the embedder, so no test makes a network
request.  What these tests pin down is the spec's two hard rules: the LLM is
reached only for pairs between the thresholds, and its answer is a suggestion
that never merges anything on its own.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import pytest

from core.entity import (
    SimilarityThresholds,
    all_pairs_count,
    candidate_pairs,
    grey_pairs,
    grey_zone_ratio,
    make_blocks,
    pending_review,
    resolve_pairs,
    review_grey_zone,
    score_pairs,
)
from core.llm import EmbeddingClient, FakeEmbeddingClient, FakeLLMClient

from tests.test_entity_embedding import REFERENCE, at_similarity


FIXTURE = Path(__file__).parent / "fixtures" / "entity_products.csv"

# One auto "same", one auto "different", one grey pair - one per block.
MIXED_RECORDS = [
    {"name": "Coca Cola 330ml"},
    {"name": "Coca Cola Kutu 330ml"},
    {"name": "Fanta Portakal 1L"},
    {"name": "Fanta Limon 1L"},
    {"name": "Eti Kek 200gr"},
    {"name": "Eti Kek Sade 200gr"},
]
MIXED_VECTORS = {
    "coca cola 330ml": REFERENCE,
    "coca cola kutu 330ml": at_similarity(0.95),
    "fanta portakal 1000ml": REFERENCE,
    "fanta limon 1000ml": at_similarity(0.30),
    "eti kek 200g": REFERENCE,
    "eti kek sade 200g": at_similarity(0.72),
}


@dataclass
class BagOfWordsEmbedder(EmbeddingClient):
    """A deterministic offline embedder: term counts over the batch vocabulary."""

    calls: list[list[str]] = field(default_factory=list)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        self.calls.append(batch)
        vocabulary = sorted({token for text in batch for token in text.split()})
        return [[float(text.split().count(token)) for token in vocabulary] for text in batch]


def answer(same: bool, confidence: float = 0.9, reason: str = "Aynı marka ve gramaj.") -> str:
    return json.dumps({"same": same, "confidence": confidence, "reason": reason})


def resolve_mixed(llm: FakeLLMClient, **kwargs) -> list:
    embedder = FakeEmbeddingClient(vectors=MIXED_VECTORS)
    return resolve_pairs(make_blocks(MIXED_RECORDS), embedder=embedder, llm=llm, **kwargs)


def test_only_grey_pairs_are_sent_to_the_llm() -> None:
    llm = FakeLLMClient(response=answer(True))

    decisions = resolve_mixed(llm)

    assert [decision.decision for decision in decisions] == ["same", "different", "same"]
    assert [decision.source for decision in decisions] == ["embedding", "embedding", "llm"]
    # Two of the three pairs were settled by code alone; only one call was made.
    assert len(llm.calls) == 1
    _, user_prompt = llm.calls[0]
    assert "eti kek sade 200g" in user_prompt
    assert "coca cola" not in user_prompt


def test_an_llm_suggestion_never_merges_on_its_own() -> None:
    llm = FakeLLMClient(response=answer(True, confidence=0.99))

    decisions = resolve_mixed(llm)

    (pair,) = grey_pairs(decisions)
    assert pair.decision == "same"
    # Advisory only: the user confirms it in the cluster review step.
    assert pair.status == "review"
    assert pair.llm_confidence == 0.99
    assert pair.reason.startswith("LLM önerisi (same)")
    # The pairs code settled on its own are the only ones that skip the user.
    assert pending_review(decisions) == [pair]


def test_the_llm_can_also_rule_a_grey_pair_out() -> None:
    llm = FakeLLMClient(response=answer(False, reason="Farklı ürün: sade ve kakaolu."))

    (pair,) = grey_pairs(resolve_mixed(llm))

    assert pair.decision == "different"
    assert pair.status == "review"
    assert "sade" in pair.reason


def test_a_fenced_json_answer_is_still_read() -> None:
    llm = FakeLLMClient(response=f"```json\n{answer(True)}\n```")

    (pair,) = grey_pairs(resolve_mixed(llm))

    assert pair.decision == "same"


@pytest.mark.parametrize(
    ("response", "expected_reason"),
    [
        ("not json at all", "geçerli JSON değil"),
        ("[1, 2, 3]", "JSON nesnesi değil"),
        ('{"same": "evet", "confidence": 0.9, "reason": "x"}', "'same' alanı boolean değil"),
        ('{"confidence": 0.9, "reason": "x"}', "'same' alanı boolean değil"),
        ('{"same": true, "confidence": "yüksek", "reason": "x"}', "'confidence' sayı değil"),
        ('{"same": true, "confidence": true, "reason": "x"}', "'confidence' sayı değil"),
        ('{"same": true, "confidence": 1.4, "reason": "x"}', "0-1 aralığında değil"),
        ('{"same": true, "confidence": 0.9}', "gerekçe yok"),
        ('{"same": true, "confidence": 0.9, "reason": "   "}', "gerekçe yok"),
        ("", "geçerli JSON değil"),
    ],
)
def test_an_unusable_answer_leaves_the_pair_for_review(response, expected_reason) -> None:
    llm = FakeLLMClient(response=response)

    (pair,) = grey_pairs(resolve_mixed(llm))

    assert pair.decision == "undecided"
    assert pair.decision != "same"
    assert pair.status == "review"
    assert expected_reason in pair.reason
    assert "incelenecek olarak kaldı" in pair.reason
    assert pair.llm_confidence is None


def test_a_low_confidence_suggestion_is_not_recorded() -> None:
    llm = FakeLLMClient(response=answer(True, confidence=0.3))

    (pair,) = grey_pairs(resolve_mixed(llm))

    assert pair.decision == "undecided"
    assert "LLM güveni 0.30" in pair.reason


def test_the_confidence_floor_is_configurable() -> None:
    llm = FakeLLMClient(response=answer(True, confidence=0.3))

    (pair,) = grey_pairs(
        resolve_mixed(llm, thresholds=SimilarityThresholds(llm_min_confidence=0.2))
    )

    assert pair.decision == "same"
    assert pair.status == "review"


def test_a_failing_provider_does_not_stop_the_batch_or_merge_the_pair() -> None:
    class BrokenLLM:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("bağlantı koptu")

    decisions = resolve_pairs(
        make_blocks(MIXED_RECORDS),
        embedder=FakeEmbeddingClient(vectors=MIXED_VECTORS),
        llm=BrokenLLM(),
    )

    assert [decision.decision for decision in decisions] == ["same", "different", "undecided"]
    assert "bağlantı koptu" in decisions[2].reason
    assert decisions[2].status == "review"


def test_the_llm_sees_the_compared_values_only_never_the_row() -> None:
    records = [
        {"name": "Eti Kek 200gr", "musteri": "Ahmet Yılmaz", "fiyat": "19,90"},
        {"name": "Eti Kek Sade 200gr", "musteri": "Ayşe Demir", "fiyat": "21,50"},
    ]
    llm = FakeLLMClient(response=answer(True))

    resolve_pairs(
        make_blocks(records),
        embedder=FakeEmbeddingClient(
            vectors={"eti kek 200g": REFERENCE, "eti kek sade 200g": at_similarity(0.72)}
        ),
        llm=llm,
    )

    (system_prompt, user_prompt) = llm.calls[0]
    payload = json.loads(user_prompt)
    assert set(payload) == {"left", "right", "embedding_similarity"}
    assert payload["left"] == {"value": "Eti Kek 200gr", "normalized": "eti kek 200g"}
    for secret in ("Ahmet", "Ayşe", "19,90", "21,50", "musteri", "fiyat"):
        assert secret not in user_prompt
    assert "advisory" in system_prompt


def test_a_pair_is_never_asked_about_twice() -> None:
    llm = FakeLLMClient(response=answer(True))
    decisions = resolve_mixed(llm)

    again = review_grey_zone(decisions, llm)

    assert len(llm.calls) == 1
    assert again == decisions


def test_the_grey_zone_stays_a_small_share_of_a_known_fixture() -> None:
    with FIXTURE.open("r", encoding="utf-8", newline="") as handle:
        products = list(csv.DictReader(handle))
    blocks = make_blocks(products)
    embedder = BagOfWordsEmbedder()
    llm = FakeLLMClient(response=answer(True))

    decisions = resolve_pairs(
        blocks,
        embedder=embedder,
        llm=llm,
        thresholds=SimilarityThresholds(high=0.90, low=0.60),
    )

    # Blocking already cut 45 possible pairs down to 6; of those, only the two
    # "Coca-Cola Kutu" comparisons land between the thresholds.
    assert len(decisions) == 6
    assert len(grey_pairs(decisions)) == 2
    assert len(llm.calls) == 2
    assert len(embedder.calls) == 1  # one batch for the whole run
    # Against the full comparison space this is the spec's ~1-5% budget.
    assert len(grey_pairs(decisions)) / all_pairs_count(len(products)) <= 0.05
    assert grey_zone_ratio(decisions) == pytest.approx(2 / 6)


def test_the_default_thresholds_need_no_llm_call_on_the_fixture() -> None:
    with FIXTURE.open("r", encoding="utf-8", newline="") as handle:
        products = list(csv.DictReader(handle))
    llm = FakeLLMClient(response=answer(True))

    decisions = resolve_pairs(make_blocks(products), embedder=BagOfWordsEmbedder(), llm=llm)

    assert grey_pairs(decisions) == []
    assert llm.calls is None or llm.calls == []
    assert all(decision.status == "auto" for decision in decisions)


def test_score_pairs_alone_never_reaches_an_llm() -> None:
    llm = FakeLLMClient(response=answer(True))

    decisions = score_pairs(
        candidate_pairs(make_blocks(MIXED_RECORDS)),
        FakeEmbeddingClient(vectors=MIXED_VECTORS),
    )

    assert llm.calls is None
    assert [decision.source for decision in decisions] == ["embedding"] * 3
