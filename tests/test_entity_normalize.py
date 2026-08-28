"""Layer 1 of entity resolution: deterministic normalization (no LLM)."""

from __future__ import annotations

import copy
from decimal import Decimal
import inspect

import pytest

from core import entity
from core.entity import DEFAULT_UNITS, NormalizationConfig, normalize


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Coca Cola 33cl", "Coca Cola 330 ml"),
        ("Coca Cola 0,33 lt", "Coca Cola 330ml"),
        ("Fanta 1 L", "Fanta 100cl"),
        ("Eti Kek 200 gr", "Eti Kek 0.2 kg"),
        ("Un 1.500,00 gr", "Un 1,5 KG"),
        ("Gofret 36 gr", "Gofret 0,036 kg"),
    ],
)
def test_unit_variants_normalize_to_the_same_key(left: str, right: str) -> None:
    assert normalize(left) == normalize(right)


def test_units_convert_to_the_documented_base_unit() -> None:
    assert normalize("Coca-Cola 33cl") == "coca cola 330ml"
    assert normalize("Ayran 0,25 LT") == "ayran 250ml"
    assert normalize("Kahve 250 GR") == "kahve 250g"
    assert normalize("Vitamin 500 mg") == "vitamin 0.5g"


def test_number_separators_follow_the_core_normalize_convention() -> None:
    assert normalize("Gofret 0,036 kg") == "gofret 36g"  # lone comma: decimal
    assert normalize("Cay 1.500 gr") == "cay 1.5g"  # lone dot: decimal, not grouping
    assert normalize("Su 1.500,00 ml") == "su 1500ml"  # grouped with decimals
    assert normalize("Kutu 1.234.567 adet") == "kutu 1234567 adet"  # two groups
    assert normalize("Kutu 1,234,567 adet") == "kutu 1234567 adet"


def test_punctuation_and_case_differences_collapse() -> None:
    assert normalize("Coca-Cola (Kutu), 33 cl.") == "coca cola kutu 330ml"
    assert normalize("COCA   COLA") == normalize("coca cola") == "coca cola"


def test_related_names_share_their_leading_tokens() -> None:
    # "Coca Cola" ~ "Coca-Cola Kutu": same normalized prefix, extra descriptor.
    plain = normalize("Coca Cola")
    variant = normalize("Coca-Cola Kutu")
    assert variant.startswith(plain)
    assert variant.split() == ["coca", "cola", "kutu"]


def test_turkish_characters_fold_deterministically() -> None:
    assert normalize("ÜLKER Çikolatalı Gofret") == "ulker cikolatali gofret"
    assert normalize("IŞIK") == normalize("ışık") == "isik"
    assert normalize("İÇECEK") == normalize("icecek") == "icecek"
    assert normalize("Pınar Süt") == normalize("PINAR SUT") == "pinar sut"


def test_abbreviations_expand_to_their_long_form() -> None:
    assert normalize("6 adt kutu") == "6 adet kutu"
    assert normalize("Su 12 pkt") == "su 12 paket"
    assert normalize("Cola 6 KT") == "cola 6 kutu"


def test_missing_and_blank_values_normalize_to_empty_string() -> None:
    assert normalize(None) == ""
    assert normalize("") == ""
    assert normalize("   ") == ""
    assert normalize("!!! ---") == ""


def test_non_string_values_are_accepted() -> None:
    assert normalize(1500) == "1500"
    assert normalize(Decimal("2.50")) == "2.50"


def test_normalization_is_deterministic() -> None:
    value = "Coca-Cola KUTU 33 cl"
    assert normalize(value) == normalize(value) == normalize(str(value))


def test_original_values_are_never_modified() -> None:
    records = [
        {"name": "Coca-Cola Kutu 33 cl", "brand": "Coca-Cola"},
        {"name": "Ülker Çikolatalı Gofret 36 gr", "brand": "Ülker"},
    ]
    snapshot = copy.deepcopy(records)

    keys = [normalize(record["name"]) for record in records]

    assert keys == ["coca cola kutu 330ml", "ulker cikolatali gofret 36g"]
    assert records == snapshot


def test_unit_and_abbreviation_tables_are_configurable() -> None:
    config = NormalizationConfig(
        units={**DEFAULT_UNITS, "kase": (Decimal(200), "ml")},
        abbreviations={"ks": "kase"},
    )

    assert normalize("Corba 2 kase", config=config) == "corba 400ml"
    assert normalize("Corba 2 ks", config=config) == "corba 2 kase"
    # The replaced table applies as given: the default expansions are gone.
    assert normalize("6 adt", config=config) == "6 adt"


def test_the_deterministic_layers_never_call_a_completion() -> None:
    for function in (
        normalize,
        entity.make_blocks,
        entity.candidate_pairs,
        entity.pair_count,
        entity.score_pairs,
    ):
        assert ".complete(" not in inspect.getsource(function)


def test_only_the_grey_zone_layer_reaches_the_llm() -> None:
    """The LLM entered the module in layer 4; it must stay confined to it."""

    callers = sorted(
        name
        for name, member in inspect.getmembers(entity, inspect.isfunction)
        if member.__module__ == entity.__name__ and ".complete(" in inspect.getsource(member)
    )

    assert callers == ["_ask_llm"]
