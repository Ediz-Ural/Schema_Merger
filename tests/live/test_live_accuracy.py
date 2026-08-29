"""Accuracy checks against a *real* provider.

The rest of the suite injects fakes, so it proves the machinery but says
nothing about whether the model picks the right column.  These tests do -- and
because they cost money and need a key, they are marked ``live`` and excluded
by default.

Run them with a key configured in ``.env``::

    SCHEMA_MERGER_LIVE=1 pytest -m live

What they assert is deliberately narrow: the matches a competent human would
call obvious must be ``auto``, and the two traps this project knows about
(an aggregate posing as a unit price, one target fed by two currencies) must
never merge unreviewed.  Model wording is never asserted.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.contracts import MappingContract, load_schema
from core.entity import cluster as build_clusters
from core.entity import make_blocks, resolve_pairs, to_cluster_plans
from core.llm import LLMConfig, LLMConfigurationError, create_embedding_client, create_llm_client
from core.matcher import match_profiles
from core.profiler import profile_file
from core.transformer import transform
from core.types import MappingEntry, SourceMatch


pytestmark = pytest.mark.live

FIXTURES = Path(__file__).parent.parent / "fixtures" / "live"
SOURCES = ["subeA_2023.csv", "export_q4.csv", "kasa_ozet.csv"]


def _requires_live() -> None:
    if os.environ.get("SCHEMA_MERGER_LIVE") != "1":
        pytest.skip("Canlı testler için SCHEMA_MERGER_LIVE=1 gerekir.")
    try:
        create_llm_client(LLMConfig.from_environment())
    except LLMConfigurationError as error:
        pytest.skip(f"Sağlayıcı yapılandırılmamış: {error}")


@pytest.fixture(scope="module")
def mapping() -> MappingContract:
    """One real Phase 1 run, shared by every assertion below (3 LLM calls)."""

    _requires_live()
    schema = load_schema(FIXTURES / "schema.yaml")
    profiles = [profile_file(FIXTURES / name) for name in SOURCES]
    return match_profiles(profiles, schema, create_llm_client())


def _sources(mapping: MappingContract, target: str) -> dict[str, SourceMatch]:
    entry = next(item for item in mapping.entries if item.target_column == target)
    return {source.file: source for source in entry.sources}


@pytest.mark.parametrize(
    "target, expected",
    [
        ("product_name", {"subeA_2023.csv": "Ürün Adı", "export_q4.csv": "item_name", "kasa_ozet.csv": "PRD"}),
        ("quantity", {"subeA_2023.csv": "Adet", "export_q4.csv": "qty", "kasa_ozet.csv": "MIKTAR"}),
        ("order_date", {"subeA_2023.csv": "Sipariş Tarihi", "export_q4.csv": "order_date", "kasa_ozet.csv": "TRH"}),
    ],
)
def test_obvious_columns_are_matched_across_languages_and_abbreviations(
    mapping: MappingContract, target: str, expected: dict[str, str]
):
    found = _sources(mapping, target)

    assert {file: source.column for file, source in found.items()} == expected
    assert [source.status for source in found.values()] == ["auto"] * len(expected)


def test_a_column_that_does_not_exist_is_left_unmatched_not_invented(mapping: MappingContract):
    customer = _sources(mapping, "customer")

    assert customer["kasa_ozet.csv"].column is None
    assert customer["kasa_ozet.csv"].status == "unmatched"
    assert customer["subeA_2023.csv"].column == "Müşteri"
    assert customer["export_q4.csv"].column == "customer_name"


def test_a_line_total_never_merges_into_unit_price_unreviewed(mapping: MappingContract):
    """`TUTAR` is 2 x 10,00 = 20,00 -- an aggregate, not a unit price."""

    kasa = _sources(mapping, "unit_price")["kasa_ozet.csv"]

    assert kasa.status != "auto", "toplam sütunu birim fiyata onaysız giremez"
    if kasa.column == "TUTAR":
        assert "toplam" in (kasa.reason or "").lower()


def test_two_currencies_feeding_one_target_are_never_merged_unreviewed(mapping: MappingContract):
    """TL and USD prices in one column would be silently incomparable."""

    prices = _sources(mapping, "unit_price")

    assert prices["subeA_2023.csv"].status != "auto"
    assert prices["export_q4.csv"].status != "auto"
    assert "USD" in (prices["subeA_2023.csv"].reason or "")


def test_entity_resolution_groups_real_spellings_with_a_real_embedder():
    """Live embeddings: three Cola spellings are one product, Pencil is not."""

    _requires_live()
    schema = load_schema(FIXTURES / "schema.yaml")
    profiles = [profile_file(FIXTURES / name) for name in SOURCES]
    proposed = match_profiles(profiles, schema, create_llm_client())
    approved = MappingContract(
        entries=[
            MappingEntry(
                target_column=entry.target_column,
                sources=[
                    source if source.status != "review" else SourceMatch(
                        file=source.file,
                        column=source.column,
                        confidence=1.0,
                        status="auto",
                        reason="Test onayı.",
                    )
                    for source in entry.sources
                ],
            )
            for entry in proposed.entries
        ]
    )

    result = transform(approved, [FIXTURES / name for name in SOURCES], schema)
    records = [
        {"name": value, "row_count": 1}
        for value in dict.fromkeys(
            str(item) for item in result.dataframe["product_name"].to_list() if item is not None
        )
    ]
    decisions = resolve_pairs(
        make_blocks(records, strategy=["prefix"]),
        embedder=create_embedding_client(),
        llm=create_llm_client(),
    )
    plans = to_cluster_plans(build_clusters(decisions, target_column="product_name"))

    grouped = {
        frozenset(member.value for member in plan.members) for plan in plans if len(plan.members) > 1
    }
    cola = {"Coca Cola 330ml", "Coca-Cola 33cl", "coca cola 0,33 lt"}
    assert cola in grouped, f"kola yazımları tek kümede olmalı: {grouped}"
    assert not any("Pencil HB" in group and "Kalem HB" in group for group in grouped)
