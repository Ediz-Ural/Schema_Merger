"""Layer 2 of entity resolution: blocking (no LLM, no all-pairs sweep)."""

from __future__ import annotations

import copy
import csv
from pathlib import Path

import pytest

from core.entity import (
    UNBLOCKED_KEY,
    BlockedRecord,
    EntityError,
    all_pairs_count,
    candidate_pairs,
    make_blocks,
    normalize,
    pair_count,
)


FIXTURE = Path(__file__).parent / "fixtures" / "entity_products.csv"


def load_products() -> list[dict[str, str]]:
    with FIXTURE.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def ids_in_block(members: list[BlockedRecord]) -> set[str]:
    return {member.record["id"] for member in members}


def block_of(blocks: dict[str, list[BlockedRecord]], product_id: str) -> str:
    for key, members in blocks.items():
        if product_id in ids_in_block(members):
            return key
    raise AssertionError(f"product {product_id} is in no block")


def test_variants_of_one_product_share_a_block() -> None:
    blocks = make_blocks(load_products())

    coca_cola = block_of(blocks, "1")
    assert ids_in_block(blocks[coca_cola]) == {"1", "2", "3"}
    assert ids_in_block(blocks[block_of(blocks, "4")]) == {"4", "5"}
    assert ids_in_block(blocks[block_of(blocks, "6")]) == {"6", "7"}


def test_unrelated_products_land_in_different_blocks() -> None:
    blocks = make_blocks(load_products())

    assert block_of(blocks, "1") != block_of(blocks, "4")  # Coca Cola vs Fanta
    assert block_of(blocks, "6") != block_of(blocks, "8")  # Ülker vs Eti
    assert block_of(blocks, "10") != block_of(blocks, "1")  # Pınar vs Coca Cola


def test_blocking_shrinks_the_comparison_space() -> None:
    products = load_products()
    blocks = make_blocks(products)

    blocked = pair_count(blocks)
    naive = all_pairs_count(len(products))

    assert blocked < naive
    assert naive == 45
    # 3 Coca Cola + 2 Fanta + 2 Ülker + 2 Eti variants -> 3 + 1 + 1 + 1 pairs.
    assert blocked == 6


def test_candidate_pairs_never_cross_a_block() -> None:
    blocks = make_blocks(load_products())

    pairs = list(candidate_pairs(blocks))

    assert len(pairs) == pair_count(blocks)
    assert all(left.block_key == right.block_key for left, right in pairs)
    assert all(left.index < right.index for left, right in pairs)


def test_unblocked_records_can_be_excluded_from_comparison() -> None:
    records = [{"name": "Coca Cola 33cl"}, {"name": "  "}, {"name": "!!!"}]

    blocks = make_blocks(records)

    assert [member.index for member in blocks[UNBLOCKED_KEY]] == [1, 2]
    assert pair_count(blocks) == 1
    assert pair_count(blocks, include_unblocked=False) == 0
    assert list(candidate_pairs(blocks, include_unblocked=False)) == []


def test_brand_strategy_groups_by_brand_spelling_variants() -> None:
    blocks = make_blocks(load_products(), strategy="brand")

    assert ids_in_block(blocks["coca cola"]) == {"1", "2", "3"}
    assert ids_in_block(blocks["ulker"]) == {"6", "7"}
    assert ids_in_block(blocks["eti"]) == {"8", "9"}


def test_category_strategy_groups_by_normalized_category() -> None:
    blocks = make_blocks(load_products(), strategy="category")

    assert ids_in_block(blocks["icecek"]) == {"1", "2", "3", "4", "5"}
    assert ids_in_block(blocks["atistirmalik"]) == {"6", "7", "8", "9"}
    assert ids_in_block(blocks["sut urunleri"]) == {"10"}


def test_composite_strategy_narrows_blocks_further() -> None:
    products = load_products()

    single = make_blocks(products, strategy="category")
    composite = make_blocks(products, strategy=("category", "prefix"))

    assert pair_count(composite) < pair_count(single)
    assert block_of(composite, "1") == "icecek|coc"
    assert block_of(composite, "1") != block_of(composite, "4")


def test_prefix_length_is_configurable() -> None:
    products = load_products()

    assert block_of(make_blocks(products, prefix_length=1), "1") == "c"
    assert block_of(make_blocks(products, prefix_length=6), "1") == "cocaco"
    # A longer prefix splits variants that differ early in the name.
    assert pair_count(make_blocks(products, prefix_length=12)) < pair_count(
        make_blocks(products, prefix_length=3)
    )


def test_plain_strings_and_objects_are_accepted() -> None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Product:
        name: str

    strings = make_blocks(["Coca Cola 33cl", "Coca-Cola 330 ml", "Fanta 1L"])
    objects = make_blocks([Product("Coca Cola 33cl"), Product("Fanta 1L")])

    assert len(strings) == 2
    assert len(objects) == 2


def test_records_are_returned_untouched() -> None:
    products = load_products()
    snapshot = copy.deepcopy(products)

    blocks = make_blocks(products, strategy=("brand", "prefix"))
    members = [member for block in blocks.values() for member in block]

    assert products == snapshot
    assert [member.record for member in members] == [
        products[member.index] for member in members
    ]
    assert all(member.record is products[member.index] for member in members)
    # The normalized key is derived, not stored back on the record.
    for member in members:
        assert member.value == products[member.index]["name"]
        assert member.normalized == normalize(member.value)


def test_every_record_is_placed_exactly_once() -> None:
    products = load_products()

    blocks = make_blocks(products)
    indexes = sorted(member.index for block in blocks.values() for member in block)

    assert indexes == list(range(len(products)))


def test_invalid_requests_are_rejected() -> None:
    products = load_products()

    with pytest.raises(EntityError, match="Unknown blocking strategy"):
        make_blocks(products, strategy="embedding")
    with pytest.raises(EntityError, match="prefix_length"):
        make_blocks(products, prefix_length=0)
    with pytest.raises(EntityError, match="At least one blocking strategy"):
        make_blocks(products, strategy=())
    with pytest.raises(EntityError, match="no 'name' field"):
        make_blocks([{"urun": "Coca Cola"}])
    with pytest.raises(EntityError, match="no 'brand' field"):
        make_blocks([{"name": "Coca Cola"}], strategy="brand")


def test_field_names_are_configurable() -> None:
    records = [
        {"urun_adi": "Coca Cola 33cl", "kategori": "İçecek"},
        {"urun_adi": "Coca-Cola 330 ml", "kategori": "icecek"},
    ]

    blocks = make_blocks(records, value_field="urun_adi", category_field="kategori", strategy="category")

    assert list(blocks) == ["icecek"]
