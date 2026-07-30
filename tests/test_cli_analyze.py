from __future__ import annotations

import json
from pathlib import Path

from cli.main import main
from core.contracts import load_mapping
from core.llm import FakeLLMClient


FIXTURES = Path(__file__).parent / "fixtures"


def _response(product_column: str, price_column: str, price_confidence: float) -> str:
    return json.dumps(
        {
            "matches": [
                {
                    "target_column": "product_name",
                    "column": product_column,
                    "confidence": 0.91,
                    "reason": "Product names and samples agree.",
                },
                {
                    "target_column": "unit_price",
                    "column": price_column,
                    "confidence": price_confidence,
                    "reason": "Price type and samples agree.",
                },
                {
                    "target_column": "stock_quantity",
                    "column": None,
                    "confidence": 0.0,
                    "reason": "This source has no stock column.",
                },
            ]
        }
    )


def test_analyze_writes_round_trippable_plan_and_summary_for_multiple_files(tmp_path, capsys):
    output = tmp_path / "mapping.yaml"
    client = FakeLLMClient(
        responses=[_response("urun", "birim_fiyat", 0.97), _response("product", "UF", 0.54)]
    )

    exit_code = main(
        [
            "analyze",
            "--inputs",
            str(FIXTURES / "sales_2023.csv"),
            str(FIXTURES / "export_q4.csv"),
            "--target-schema",
            str(FIXTURES / "schema.yaml"),
            "--out",
            str(output),
        ],
        llm_client=client,
    )

    assert exit_code == 0
    assert len(client.calls or []) == 2
    mapping = load_mapping(output)
    assert [entry.target_column for entry in mapping.entries] == [
        "product_name",
        "unit_price",
        "stock_quantity",
    ]
    assert [(source.status, source.column) for source in mapping.entries[1].sources] == [
        ("auto", "birim_fiyat"),
        ("review", "UF"),
    ]
    assert capsys.readouterr().out.splitlines() == [
        "\u2713 3 s\u00fctun otomatik e\u015fle\u015fti",
        "\u26a0 1 s\u00fctun onay bekliyor (review)",
        "\u2717 2 s\u00fctun hi\u00e7bir dosyada bulunamad\u0131",
        f"\u2192 Plan\u0131 d\u00fczenle: {output}, sonra: merger apply",
    ]


def test_analyze_reports_missing_input_without_creating_a_plan(tmp_path, capsys):
    output = tmp_path / "mapping.yaml"

    exit_code = main(
        [
            "analyze",
            "--inputs",
            str(tmp_path / "missing.csv"),
            "--target-schema",
            str(FIXTURES / "schema.yaml"),
            "--out",
            str(output),
        ],
        llm_client=FakeLLMClient(),
    )

    assert exit_code == 2
    assert "Input file does not exist" in capsys.readouterr().out
    assert not output.exists()


def test_analyze_reports_invalid_schema_without_creating_a_plan(tmp_path, capsys):
    schema = tmp_path / "invalid-schema.yaml"
    schema.write_text("target_columns: []\n", encoding="utf-8")
    output = tmp_path / "mapping.yaml"

    exit_code = main(
        [
            "analyze",
            "--inputs",
            str(FIXTURES / "sales_2023.csv"),
            "--target-schema",
            str(schema),
            "--out",
            str(output),
        ],
        llm_client=FakeLLMClient(),
    )

    assert exit_code == 2
    assert "zorunlu alan eksik: output" in capsys.readouterr().out
    assert not output.exists()
