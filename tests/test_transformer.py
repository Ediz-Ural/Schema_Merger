from __future__ import annotations

from pathlib import Path

import polars as pl

from core.transformer import transform


FIXTURES = Path(__file__).parent / "fixtures"


def test_transformer_vertically_unions_rows_normalizes_values_and_keeps_provenance():
    result = transform(
        FIXTURES / "transform_mapping.yaml",
        [FIXTURES / "transform_sales_tr.csv", FIXTURES / "transform_export_en.csv"],
        FIXTURES / "transform_schema.yaml",
        chunk_size=1,
    )

    assert result.dataframe.schema == {
        "product_name": pl.String,
        "unit_price": pl.Float64,
        "sold_on": pl.Date,
        "stock_quantity": pl.Int64,
    }
    assert result.dataframe.height == 4
    assert result.dataframe["product_name"].to_list() == ["Kalem", "Defter", "Pencil", "Notebook"]
    assert result.dataframe["unit_price"].to_list() == [12.5, 1234.56, 8.9, 10.0]
    assert [value.isoformat() for value in result.dataframe["sold_on"].to_list()] == [
        "2024-01-31",
        "2024-02-01",
        "2024-03-15",
        "2024-03-16",
    ]
    assert result.dataframe["stock_quantity"].to_list() == [None, None, None, None]
    assert result.provenance["source_file"].to_list() == [
        "transform_sales_tr.csv",
        "transform_sales_tr.csv",
        "transform_export_en.csv",
        "transform_export_en.csv",
    ]
    assert result.provenance["unit_price"].to_list() == ["fiyat", "fiyat", "price", "price"]
    assert result.provenance["stock_quantity"].null_count() == 4
    assert result.conversion_error_count == 0


def test_invalid_conversions_become_null_and_are_counted_without_losing_rows(tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("amount;day\nnot-a-number;not-a-date\n12,50;31.01.2024\n", encoding="utf-8")
    schema = tmp_path / "schema.yaml"
    schema.write_text(
        """target_columns:
  - name: amount
    type: decimal
    required: true
  - name: day
    type: date
    required: true
output:
  format: csv
  add_provenance: true
""",
        encoding="utf-8",
    )
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(
        """- target_column: amount
  sources:
    - file: bad.csv
      column: amount
      confidence: 1.0
      status: auto
- target_column: day
  sources:
    - file: bad.csv
      column: day
      confidence: 1.0
      status: auto
""",
        encoding="utf-8",
    )

    result = transform(mapping, [source], schema)

    assert result.row_count == 2
    assert result.dataframe["amount"].to_list() == [None, 12.5]
    assert result.dataframe["day"].to_list()[0] is None
    assert result.conversion_error_counts == {"amount": 1, "day": 1}
