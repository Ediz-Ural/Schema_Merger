from pathlib import Path

import pytest

from core.contracts import ContractValidationError, dump_mapping, load_mapping, load_schema


FIXTURES = Path(__file__).parent / "fixtures"


def test_schema_fixture_is_parsed():
    schema = load_schema(FIXTURES / "schema.yaml")

    assert [column.name for column in schema.target_columns] == ["product_name", "unit_price", "stock_quantity"]
    assert schema.output.format == "xlsx"
    assert schema.output.add_provenance is True


def test_mapping_round_trip_is_lossless(tmp_path):
    source = tmp_path / "mapping.yaml"
    source.write_text(
        """- target_column: unit_price
  sources:
    - file: sales_2023.xlsx
      column: birim_fiyat
      confidence: 0.97
      status: auto
      reason: isim ve tip uyuyor
      samples: [12.50, 8.90]
- target_column: product_name
  sources:
    - file: export_q4.csv
      column: null
      confidence: 0.0
      status: unmatched
      reason: karşılık yok
""",
        encoding="utf-8",
    )
    loaded = load_mapping(source)
    destination = tmp_path / "round_trip.yaml"

    dump_mapping(loaded, destination)

    assert load_mapping(destination) == loaded


def test_invalid_status_is_rejected(tmp_path):
    mapping = tmp_path / "invalid-status.yaml"
    mapping.write_text(
        "- target_column: product_name\n  sources:\n    - file: sales.csv\n      column: urun\n      confidence: 0.8\n      status: maybe\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError, match="status geçersiz"):
        load_mapping(mapping)


def test_missing_required_mapping_field_is_rejected(tmp_path):
    mapping = tmp_path / "missing-field.yaml"
    mapping.write_text(
        "- target_column: product_name\n  sources:\n    - file: sales.csv\n      column: urun\n      status: auto\n",
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError, match="zorunlu alan eksik: confidence"):
        load_mapping(mapping)
