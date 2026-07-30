from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from core.contracts import load_schema
from core.llm import FakeLLMClient
from core.matcher import MatchThresholds, match_profiles
from core.profiler import profile_file


FIXTURES = Path(__file__).parent / "fixtures"


def response_for(product_column: str, price_column: str, price_confidence: float) -> str:
    return json.dumps(
        {
            "matches": [
                {
                    "target_column": "product_name",
                    "column": product_column,
                    "confidence": 0.91,
                    "reason": "İsim, metin tipi ve ürün örnekleri uyuyor.",
                },
                {
                    "target_column": "unit_price",
                    "column": price_column,
                    "confidence": price_confidence,
                    "reason": "Fiyat tipi ve örnek değerler uyuyor.",
                },
                {
                    "target_column": "stock_quantity",
                    "column": None,
                    "confidence": 0.0,
                    "reason": "Bu kaynakta stok sütunu yok.",
                },
            ]
        }
    )


def mapping_by_target(mapping, target_name):
    return next(entry for entry in mapping.entries if entry.target_column == target_name)


def test_profiles_produce_expected_auto_review_and_unmatched_mapping():
    schema = load_schema(FIXTURES / "schema.yaml")
    sources = [profile_file(FIXTURES / "sales_2023.csv"), profile_file(FIXTURES / "export_q4.csv")]
    client = FakeLLMClient(
        responses=[response_for("urun", "birim_fiyat", 0.97), response_for("product", "UF", 0.54)]
    )

    mapping = match_profiles(sources, schema, client)

    unit_price = mapping_by_target(mapping, "unit_price").sources
    assert [(source.column, source.status) for source in unit_price] == [
        ("birim_fiyat", "auto"),
        ("UF", "review"),
    ]
    assert unit_price[1].samples == ["12.50", "8.90", "15.00"]
    stock = mapping_by_target(mapping, "stock_quantity").sources
    assert all(source.status == "unmatched" and source.samples == [] for source in stock)
    assert len(client.calls or []) == 2


def test_prompt_contains_profile_samples_and_statistics():
    schema = load_schema(FIXTURES / "schema.yaml")
    client = FakeLLMClient(response=response_for("urun", "birim_fiyat", 0.97))

    match_profiles([profile_file(FIXTURES / "sales_2023.csv")], schema, client)

    system, user = (client.calls or [])[0]
    assert "vertical union" in system
    assert '"samples": ["Kalem", "Defter", "Silgi"]' in user
    assert '"unique_count": 3' in user


def test_malformed_llm_response_becomes_review_without_crashing():
    schema = load_schema(FIXTURES / "schema.yaml")
    client = FakeLLMClient(response="this is not json")

    mapping = match_profiles([profile_file(FIXTURES / "sales_2023.csv")], schema, client)

    assert all(entry.sources[0].status == "review" for entry in mapping.entries)
    assert all(entry.sources[0].samples == [] for entry in mapping.entries)
    assert all("geçerli JSON değil" in (entry.sources[0].reason or "") for entry in mapping.entries)


def test_request_count_is_independent_of_source_row_count():
    schema = load_schema(FIXTURES / "schema.yaml")
    short_profile = profile_file(FIXTURES / "sales_2023.csv")
    large_profile = replace(
        short_profile,
        tables=[replace(short_profile.tables[0], row_count=1_000_000)],
    )

    short_client = FakeLLMClient(response=response_for("urun", "birim_fiyat", 0.97))
    large_client = FakeLLMClient(response=response_for("urun", "birim_fiyat", 0.97))
    match_profiles([short_profile], schema, short_client)
    match_profiles([large_profile], schema, large_client)

    assert len(short_client.calls or []) == len(large_client.calls or []) == 1


def test_auto_threshold_is_configurable():
    schema = load_schema(FIXTURES / "schema.yaml")
    client = FakeLLMClient(response=response_for("urun", "birim_fiyat", 0.91))

    mapping = match_profiles(
        [profile_file(FIXTURES / "sales_2023.csv")],
        schema,
        client,
        thresholds=MatchThresholds(auto_confidence=0.95),
    )

    assert mapping_by_target(mapping, "unit_price").sources[0].status == "review"
