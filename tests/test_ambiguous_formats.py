import pytest
from modules.evaluator import build_executive_horizon


def test_roman_numeral_quarter_vs_month_ambiguity():
    """Demonstrate ambiguity: 'II 2026' without 'kw' or 'kwartał' is parsed as February,

    while 'II kw. 2026' is parsed as Q2.
    """
    # 'II kw. 2026' explicitly denotes quarter
    horizon_q = build_executive_horizon(["II kw. 2026"])
    assert "II kw. 2026 (PKB)" in horizon_q

    # 'II 2026' without 'kw' falls into roman_to_month and is treated as February (luty)
    horizon_m = build_executive_horizon(["II 2026"])
    assert "Luty 2026 (dane miesięczne)" in horizon_m
    assert "kw." not in horizon_m


def test_roman_numeral_iv_ambiguity():
    """Demonstrate ambiguity: 'IV 2026' is treated as April rather than Q4 if kw marker is absent."""
    horizon_m = build_executive_horizon(["IV 2026"])
    assert "Kwiecień 2026 (dane miesięczne)" in horizon_m

    horizon_q = build_executive_horizon(["IV kw. 2026"])
    assert "IV kw. 2026 (PKB)" in horizon_q


def test_numeric_date_delimiter_ambiguity():
    """Demonstrate ambiguity in DD.MM.YYYY vs MM.DD.YYYY:

    regex r'\\b(0?[1-9]|1[0-2])\\b[\\.\\/\\-]' captures the FIRST number <= 12.
    For '05.06.2026', Polish format is 5th of June (month 6),
    but the regex captures '05' as month 5 (maj).
    """
    # 05.06.2026 in Poland is 5 June 2026.
    horizon = build_executive_horizon(["05.06.2026"])
    # Regex matched '05.' as month 5 -> 'Maj 2026 (dane miesięczne)'
    assert "Maj 2026 (dane miesięczne)" in horizon
    assert "czerwiec" not in horizon.lower()


def test_periods_lacking_four_digit_year_are_ignored():
    """Demonstrate that periods lacking a 4-digit year (e.g. 'lipiec', 'II kw.')

    are skipped completely by build_executive_horizon.
    """
    # Period has no year
    horizon = build_executive_horizon(["lipiec", "II kw.", "sierpień"])
    # None of them matched 20\\d{2}, so default fallback is returned
    assert horizon == "Bieżące odczyty GUS i NBP"


def test_baseline_indicator_name_variations(baseline_db_ro_connection):
    """Verify known baseline indicator name variations present in collected_indicators."""
    cur = baseline_db_ro_connection.cursor()
    cur.execute("SELECT DISTINCT indicator_name FROM collected_indicators")
    names = {row[0] for row in cur.fetchall()}

    # Verify inflation variants in baseline
    core_cpi_variants = {
        "Inflacja bazowa (po wyłączeniu cen żywności i energii)",
        "Inflacja bazowa (wyłączenie cen żywności i energii)",
        "Inflacja bazowa (z wyłączeniem cen żywności i energii)",
    }
    assert core_cpi_variants.issubset(names), "Expected all 3 core inflation variants in baseline"

    # Verify unemployment variants in baseline
    unemployment_variants = {
        "Stopa bezrobocia",
        "Stopa bezrobocia rejestrowanego",
        "Stopa bezrobocia rejestrowanego (GUS)",
        "Liczba bezrobotnych",
        "Liczba zarejestrowanych bezrobotnych",
    }
    assert unemployment_variants.issubset(names), "Expected unemployment variants in baseline"

    # Verify GDP variants in baseline
    gdp_variants = {
        "PKB r/r",
        "Produkt Krajowy Brutto r/r",
        "Produkt Krajowy Brutto kw/kw",
    }
    assert gdp_variants.issubset(names), "Expected GDP variants in baseline"
