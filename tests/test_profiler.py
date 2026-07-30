from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.profiler import ProfileError, profile_file


FIXTURES = Path(__file__).parent / "fixtures"


def column(profile, name):
    return next(item for item in profile.tables[0].columns if item.name == name)


def test_csv_produces_a_profile_for_each_column_and_correct_statistics():
    profile = profile_file(FIXTURES / "sample_tr.csv")

    assert profile.tables[0].name == "sample_tr"
    assert [item.name for item in profile.tables[0].columns] == ["urun", "fiyat", "adet", "tarih", "aktif"]
    price = column(profile, "fiyat")
    assert price.inferred_type == "decimal"
    assert price.format_pattern == "mixed_numeric"
    assert price.minimum == 12.5
    assert price.maximum == 1234.56
    assert price.unique_count == 2
    assert price.null_ratio == pytest.approx(1 / 3)
    assert column(profile, "adet").inferred_type == "integer"
    assert column(profile, "tarih").inferred_type == "date"
    assert column(profile, "aktif").inferred_type == "boolean"


def test_turkish_decimal_formats_are_detected_as_decimal(tmp_path):
    path = tmp_path / "numbers.csv"
    path.write_text("amount;label\n12,50;one\n1.234,56;two\n", encoding="utf-8")

    result = profile_file(path)
    assert column(result, "amount").inferred_type == "decimal"
    assert column(result, "amount").format_pattern == "mixed_numeric"


def test_xlsx_profiles_all_sheets_or_a_selected_one():
    all_sheets = profile_file(FIXTURES / "sample_multi_sheet.xlsx")
    assert [table.name for table in all_sheets.tables] == ["Sales", "Stok"]
    selected = profile_file(FIXTURES / "sample_multi_sheet.xlsx", sheet="Stok")
    assert [table.name for table in selected.tables] == ["Stok"]
    assert column(selected, "stok").inferred_type == "integer"


def test_bad_or_unsupported_files_have_clear_errors(tmp_path):
    unsupported = tmp_path / "source.json"
    unsupported.write_text("{}", encoding="utf-8")
    with pytest.raises(ProfileError, match="Only .csv and .xlsx"):
        profile_file(unsupported)

    broken = tmp_path / "broken.xlsx"
    broken.write_text("not an xlsx", encoding="utf-8")
    with pytest.raises(ProfileError, match="Could not read Excel"):
        profile_file(broken)
