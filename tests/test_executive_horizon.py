import pytest
from modules.evaluator import build_executive_horizon


def test_horizon_empty_or_none_returns_default():
    """Empty or null periods must return the standard institutional fallback."""
    assert build_executive_horizon([]) == "Bieżące odczyty GUS i NBP"
    assert build_executive_horizon([None, "", "brak danych", "none", "  "]) == "Bieżące odczyty GUS i NBP"


def test_horizon_single_month():
    """Single month in a year formats as (dane miesięczne)."""
    result = build_executive_horizon(["lipiec 2026"])
    assert result == "Lipiec 2026 (dane miesięczne)"


def test_horizon_multiple_months_formats_range():
    """Two or more months in latest year formats as month range (wskaźniki miesięczne)."""
    # Two months
    result2 = build_executive_horizon(["czerwiec 2026", "lipiec 2026"])
    assert result2 == "Czerwiec – lipiec 2026 (wskaźniki miesięczne)"

    # Three months - should take the last two
    result3 = build_executive_horizon(["maj 2026", "czerwiec 2026", "lipiec 2026"])
    assert result3 == "Czerwiec – lipiec 2026 (wskaźniki miesięczne)"


def test_horizon_roman_numeral_months():
    """Roman numerals mapped to months produce capitalized Polish month names."""
    result = build_executive_horizon(["VII 2026", "VIII 2026"])
    assert result == "Lipiec – sierpień 2026 (wskaźniki miesięczne)"


def test_horizon_quarter_detection():
    """Quarters with 'kw.' or 'kwartał' are formatted with '(PKB)' tag."""
    assert build_executive_horizon(["II kw. 2026"]) == "II kw. 2026 (PKB)"
    assert build_executive_horizon(["iii kwartał 2026"]) == "III kw. 2026 (PKB)"
    assert build_executive_horizon(["iv kwartał 2026"]) == "IV kw. 2026 (PKB)"

    # Note known limitation: Arabic 'q3' produces '3 kw.' rather than 'III kw.'
    # because roman_to_q only defines keys: i, ii, iii, iv
    assert build_executive_horizon(["q3 kwartał 2026"]) == "3 kw. 2026 (PKB)"


def test_horizon_reference_years_included():
    """Past years earlier than max(years) are listed in reference base section."""
    result = build_executive_horizon(["VII 2025", "VIII 2026"])
    assert "baza odniesienia: 2025 r." in result

    result_multi_year = build_executive_horizon(["2023", "2024", "VII 2025", "VIII 2026"])
    assert "baza odniesienia: 2023, 2024, 2025 r." in result_multi_year


def test_horizon_combined_macro_structure():
    """Combined input containing months, quarter, and past year produces three pipe-delimited segments."""
    raw_periods = ["II kw. 2026", "lipiec 2026", "sierpień 2026", "XI 2025"]
    result = build_executive_horizon(raw_periods)

    expected = "Lipiec – sierpień 2026 (wskaźniki miesięczne) | II kw. 2026 (PKB) | baza odniesienia: 2025 r."
    assert result == expected


def test_horizon_with_actual_baseline_database_periods(baseline_db_ro_connection):
    """Verify build_executive_horizon execution against all real raw periods stored in the baseline database."""
    cur = baseline_db_ro_connection.cursor()
    cur.execute("SELECT DISTINCT period FROM collected_indicators")
    baseline_periods = [row[0] for row in cur.fetchall()]

    result = build_executive_horizon(baseline_periods)
    assert "2026" in result
    assert "II kw. 2026 (PKB)" in result
    assert "baza odniesienia: 2025 r." in result
