"""Semantic guards: what a match *means*, not just what type it has.

These are the traps a type check passes and a merge then hides -- a line total
filling a unit price, one target column fed by two currencies.  The guard is
deterministic and one-directional: it may send an ``auto`` match to review, and
it may never approve one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.contracts import MappingContract, load_schema
from core.llm import FakeLLMClient
from core.matcher import match_profiles
from core.profiler import profile_file
from core.semantics import apply_semantic_guards
from core.types import ColumnProfile, FileProfile, MappingEntry, SourceMatch, TableProfile


FIXTURES = Path(__file__).parent / "fixtures"


def column(name: str, samples: list[object] | None = None) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        inferred_type="decimal",
        samples=samples or ["12,50"],
        unique_count=3,
        null_ratio=0.0,
    )


def profile(file_name: str, *columns: ColumnProfile) -> FileProfile:
    return FileProfile(
        path=Path(file_name),
        tables=[TableProfile(name=file_name, row_count=3, columns=list(columns))],
    )


def plan(target: str, *sources: SourceMatch) -> MappingContract:
    return MappingContract(entries=[MappingEntry(target_column=target, sources=list(sources))])


def match(file: str, column_name: str, status: str = "auto", confidence: float = 0.96) -> SourceMatch:
    return SourceMatch(
        file=file,
        column=column_name,
        confidence=confidence,
        status=status,
        reason="Tür ve örnekler uyuşuyor.",
    )


def statuses(mapping: MappingContract, target: str) -> list[tuple[str | None, str]]:
    entry = next(item for item in mapping.entries if item.target_column == target)
    return [(source.column, source.status) for source in entry.sources]


@pytest.mark.parametrize("source_column", ["TUTAR", "toplam_tutar", "line_total", "SUBTOTAL"])
def test_an_aggregate_column_never_fills_a_unit_price_on_its_own(source_column: str):
    mapping = plan("unit_price", match("kasa.csv", source_column))

    guarded = apply_semantic_guards(mapping, [profile("kasa.csv", column(source_column))])

    assert statuses(guarded, "unit_price") == [(source_column, "review")]
    reason = guarded.entries[0].sources[0].reason or ""
    assert "toplam" in reason and "birim" in reason


def test_the_reverse_trap_is_caught_too():
    mapping = plan("toplam_tutar", match("kasa.csv", "birim_fiyat"))

    guarded = apply_semantic_guards(mapping, [profile("kasa.csv", column("birim_fiyat"))])

    assert statuses(guarded, "toplam_tutar") == [("birim_fiyat", "review")]


@pytest.mark.parametrize("source_column", ["birim_fiyat", "unit_price", "price"])
def test_a_genuine_unit_price_is_left_alone(source_column: str):
    mapping = plan("unit_price", match("sales.csv", source_column))

    guarded = apply_semantic_guards(mapping, [profile("sales.csv", column(source_column))])

    assert statuses(guarded, "unit_price") == [(source_column, "auto")]


def test_a_column_pair_with_no_money_word_is_not_the_guard_s_business():
    mapping = plan("quantity", match("sales.csv", "toplam_adet"))

    guarded = apply_semantic_guards(mapping, [profile("sales.csv", column("toplam_adet"))])

    assert statuses(guarded, "quantity") == [("toplam_adet", "auto")]


def test_two_currencies_feeding_one_target_go_to_review():
    mapping = plan(
        "unit_price",
        match("subeA.csv", "Birim Fiyat (TL)"),
        match("export.csv", "price_usd"),
    )
    profiles = [
        profile("subeA.csv", column("Birim Fiyat (TL)")),
        profile("export.csv", column("price_usd", ["8.90"])),
    ]

    guarded = apply_semantic_guards(mapping, profiles)

    assert statuses(guarded, "unit_price") == [
        ("Birim Fiyat (TL)", "review"),
        ("price_usd", "review"),
    ]
    assert "TL ve USD" in (guarded.entries[0].sources[0].reason or "")


def test_a_currency_is_also_read_from_sample_values():
    mapping = plan(
        "unit_price",
        match("a.csv", "fiyat"),
        match("b.csv", "fiyat"),
    )
    profiles = [
        profile("a.csv", column("fiyat", ["12,50 ₺"])),
        profile("b.csv", column("fiyat", ["$8.90"])),
    ]

    guarded = apply_semantic_guards(mapping, profiles)

    assert statuses(guarded, "unit_price") == [("fiyat", "review"), ("fiyat", "review")]


def test_one_currency_everywhere_is_not_a_conflict():
    mapping = plan("unit_price", match("a.csv", "fiyat_tl"), match("b.csv", "birim_fiyat_tl"))
    profiles = [profile("a.csv", column("fiyat_tl")), profile("b.csv", column("birim_fiyat_tl"))]

    guarded = apply_semantic_guards(mapping, profiles)

    assert statuses(guarded, "unit_price") == [("fiyat_tl", "auto"), ("birim_fiyat_tl", "auto")]


def test_the_guard_only_lowers_trust_and_never_raises_it():
    mapping = plan(
        "unit_price",
        SourceMatch(file="a.csv", column=None, confidence=0.0, status="unmatched", reason="Yok."),
        SourceMatch(file="b.csv", column="TUTAR", confidence=0.4, status="review", reason="Emin değilim."),
    )

    guarded = apply_semantic_guards(mapping, [profile("b.csv", column("TUTAR"))])

    assert statuses(guarded, "unit_price") == [(None, "unmatched"), ("TUTAR", "review")]


def test_a_demoted_match_keeps_the_model_s_reason_and_gains_samples():
    mapping = plan("unit_price", match("kasa.csv", "TUTAR"))

    guarded = apply_semantic_guards(mapping, [profile("kasa.csv", column("TUTAR", ["20,00", "44,50"]))])

    demoted = guarded.entries[0].sources[0]
    assert "Tür ve örnekler uyuşuyor." in (demoted.reason or "")
    assert demoted.samples == ["20,00", "44,50"]
    assert demoted.confidence == 0.96


def test_the_guard_runs_inside_the_matcher_pipeline():
    """A confident LLM proposal is still reviewed when its meaning is suspect."""

    schema = load_schema(FIXTURES / "schema.yaml")
    sources = [profile_file(FIXTURES / "sales_2023.csv")]
    response = json.dumps(
        {
            "matches": [
                {
                    "target_column": "product_name",
                    "column": "urun",
                    "confidence": 0.95,
                    "reason": "Adlar örtüşüyor.",
                },
                {
                    "target_column": "unit_price",
                    "column": "birim_fiyat",
                    "confidence": 0.98,
                    "reason": "Ondalık örnekler örtüşüyor.",
                },
                {
                    "target_column": "stock_quantity",
                    "column": None,
                    "confidence": 0.0,
                    "reason": "Stok sütunu yok.",
                },
            ]
        }
    )

    mapping = match_profiles(sources, schema, FakeLLMClient(response=response))

    assert statuses(mapping, "unit_price") == [("birim_fiyat", "auto")]
