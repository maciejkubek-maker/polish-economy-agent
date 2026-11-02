"""
Testy jednostkowe i integracyjne dla modułu konektorów oficjalnych API (TASK-05).
Plik: tests/test_connectors.py

Wymagania:
- 100% testów działa offline bez połączenia z siecią i bez płatnych API (mock fixtures).
- Weryfikacja NBP (REST EUR/USD oraz XML stóp procentowych).
- Weryfikacja Eurostat:
  * JSON-stat 2.0 dla HICP i bezrobocia BAEL.
  * Wielowymiarowy parser z kalkulacją strides oraz kontrolą kompletności danych.
  * Obsługa aktualnej serii HICP z tabeli teicp000 (COICOP 2018).
  * Obsługa archiwalnej serii HICP z prc_hicp_manr (COICOP 1999).
  * Test świeżości danych (blokowanie prezentowania odczytu z 2025 r. jako aktualnego w 2026 r. - StaleDataError).
  * Wyraźne rozdzielenie poziomu PKB (CLV10_MEUR -> PL_GDP_VOLUME, unit=MEUR)
    od dynamiki kw/kw (PCH_PRE -> PL_GDP_QOQ, unit=PCT) i r/r (PCH_SM_PR_Y -> PL_GDP_YOY, unit=PCT).
  * Zakaz zapisywania poziomu wolumenu jako PL_GDP_QOQ.
  * Rozdzielenie period_end od daty publikacji (publication_date=None, gdy API nie podaje daty publikacji).
- Weryfikacja GUS:
  * BDL: var_id 60270 (szereg roczny ANNUAL), wyszukiwanie zmiennych.
  * Wycofanie 60269 z VERIFIED_BDL_VARIABLES, blokowanie pobierania bez zweryfikowanego ID (VariableNotMappedError).
  * Rygor braku arbitralnego oznaczania zmiennej jako VERIFIED: podanie samego var_id pozostawia status NOT_VERIFIED;
    wymagany jest komplet zweryfikowanego mapowania (ID, definicja, jednostka, częstotliwość).
  * DBW: ścisłe ustalanie miesiąca z metadanych okresu (zakaz rocznego zakresu dla wskaźnika miesięcznego).
  * DBW: przeliczanie indeksu bazy 100 na stopę procentową oparte na potwierdzonej metodologii (usunięcie heurystyk numerycznych).
  * Rozdzielenie period_end od daty publikacji.
- Rygorystyczny test zakazu fikcyjnych ID (VariableNotMappedError).
- Weryfikacja odporności na błędy: retry, timeout, 404 (DataNotFoundError), walidacja zakresów.
"""

from decimal import Decimal
import json
import pytest

from modules.connectors.base import (
    BaseConnector,
    ConnectorException,
    DataNotFoundError,
    MacroObservation,
    RawEvidence,
    StaleDataError,
    ValidationError,
    VariableNotMappedError,
)
from modules.connectors.nbp import NbpConnector
from modules.connectors.eurostat import EurostatConnector
from modules.connectors.gus import GusConnector


# ==============================================================================
# FIXTURES DANYCH TESTOWYCH (OFFLINE PAYLOADS)
# ==============================================================================

NBP_EUR_JSON = """
{
  "table": "A",
  "currency": "euro",
  "code": "EUR",
  "rates": [
    {
      "no": "212/A/NBP/2026",
      "effectiveDate": "2026-10-30",
      "mid": 4.3450
    }
  ]
}
"""

NBP_USD_JSON = """
{
  "table": "A",
  "currency": "dolar amerykański",
  "code": "USD",
  "rates": [
    {
      "no": "212/A/NBP/2026",
      "effectiveDate": "2026-10-30",
      "mid": 4.0215
    }
  ]
}
"""

NBP_RATES_XML = """<?xml version="1.0" encoding="utf-8"?>
<stopy_procentowe>
    <pozycja id="ref" obowiazuje_od="2023-10-05" oprocentowanie="5.75"/>
    <pozycja id="lom" obowiazuje_od="2023-10-05" oprocentowanie="6.25"/>
    <pozycja id="dep" obowiazuje_od="2023-10-05" oprocentowanie="5.25"/>
    <pozycja id="red" obowiazuje_od="2023-10-05" oprocentowanie="5.80"/>
    <pozycja id="dys" obowiazuje_od="2023-10-05" oprocentowanie="5.85"/>
</stopy_procentowe>
"""

# Fixture dla bieżącej serii HICP z teicp000 (COICOP 2018 - 2026 r.)
EUROSTAT_TEICP000_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "HICP - monthly data (annual rate of change - COICOP 2018)",
  "id": ["freq", "coicop18", "unit", "geo", "time"],
  "size": [1, 1, 2, 1, 3],
  "dimension": {
    "freq": {"category": {"index": {"M": 0}}},
    "coicop18": {"category": {"index": {"TOTAL": 0}}},
    "unit": {"category": {"index": {"PCH_M1": 0, "PCH_M12": 1}}},
    "geo": {"category": {"index": {"PL": 0}}},
    "time": {
      "category": {
        "index": {
          "2026-07": 0,
          "2026-08": 1,
          "2026-09": 2
        }
      }
    }
  },
  "value": {
    "0": 0.2, "1": 0.1, "2": 0.3,
    "3": 3.1, "4": 3.5, "5": 4.0
  }
}
"""

# Fixture dla archiwalnej serii HICP z prc_hicp_manr (COICOP 1999 - zamrożona na 2025-12)
EUROSTAT_HICP_ARCHIVAL_2025_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "HICP - monthly data (annual rate of change - COICOP 1999 archival)",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "coicop": {"category": {"index": ["CP00"]}},
    "unit": {"category": {"index": ["RCH_A"]}},
    "time": {
      "category": {
        "index": {
          "2025M10": 0,
          "2025M11": 1,
          "2025M12": 2
        }
      }
    }
  },
  "value": {
    "0": 2.8,
    "1": 2.6,
    "2": 2.5
  }
}
"""

# Kompatybilność wsteczna z bazowym fixture prc_hicp_manr
EUROSTAT_HICP_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "HICP - monthly data (annual rate of change)",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "coicop": {"category": {"index": ["CP00"]}},
    "unit": {"category": {"index": ["RCH_A"]}},
    "time": {
      "category": {
        "index": {
          "2026M07": 0,
          "2026M08": 1,
          "2026M09": 2
        }
      }
    }
  },
  "value": {
    "0": 4.2,
    "1": 4.3,
    "2": 4.5
  }
}
"""

EUROSTAT_UNEMPLOYMENT_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "Unemployment by sex and age - monthly data",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "time": {
      "category": {
        "index": {
          "2026M08": 0,
          "2026M09": 1
        }
      }
    }
  },
  "value": {
    "0": 3.0,
    "1": 2.9
  }
}
"""

# Fixture dla wolumenu PKB w mln EUR (unit=CLV10_MEUR)
EUROSTAT_GDP_VOLUME_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "Gross domestic product at market prices (volumes)",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "time": {
      "category": {
        "index": {
          "2026-Q1": 0,
          "2026-Q2": 1
        }
      }
    }
  },
  "value": {
    "0": 135400.5,
    "1": 136850.2
  }
}
"""

# Fixture dla dynamiki kw/kw PKB w % (unit=PCH_PRE)
EUROSTAT_GDP_GROWTH_QOQ_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "Gross domestic product - percentage change on previous period",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "time": {
      "category": {
        "index": {
          "2026-Q1": 0,
          "2026-Q2": 1
        }
      }
    }
  },
  "value": {
    "0": 0.8,
    "1": 1.1
  }
}
"""

# Fixture dla dynamiki r/r PKB w % (unit=PCH_SM_PR_Y)
EUROSTAT_GDP_GROWTH_YOY_JSON = """
{
  "version": "2.0",
  "class": "dataset",
  "label": "Gross domestic product - percentage change compared to same period in previous year",
  "dimension": {
    "geo": {"category": {"index": ["PL"]}},
    "time": {
      "category": {
        "index": {
          "2026-Q1": 0,
          "2026-Q2": 1
        }
      }
    }
  },
  "value": {
    "0": 3.4,
    "1": 3.9
  }
}
"""

GUS_BDL_UNEMPLOYMENT_JSON = """
{
  "totalRecords": 1,
  "page": 0,
  "pageSize": 10,
  "variable": {
    "id": 60270,
    "subjectId": "P2437",
    "n1": "ogółem",
    "level": 6,
    "measureUnitId": 5,
    "measureUnitName": "%"
  },
  "results": [
    {
      "id": "000000000000",
      "name": "POLSKA",
      "values": [
        {
          "year": 2025,
          "val": 5.1,
          "attrId": 1
        },
        {
          "year": 2026,
          "month": 8,
          "val": 5.0,
          "attrId": 1
        }
      ]
    }
  ]
}
"""

GUS_BDL_COUNT_JSON = """
{
  "totalRecords": 1,
  "page": 0,
  "pageSize": 10,
  "results": [
    {
      "id": "000000000000",
      "name": "POLSKA",
      "values": [
        {
          "year": 2026,
          "val": 845.3,
          "attrId": 1
        }
      ]
    }
  ]
}
"""

GUS_BDL_SEARCH_JSON = """
{
  "totalRecords": 2,
  "page": 0,
  "pageSize": 10,
  "results": [
    {
      "id": 60270,
      "subjectId": "P2437",
      "n1": "Stopa bezrobocia rejestrowanego",
      "measureUnitName": "%"
    },
    {
      "id": 60269,
      "subjectId": "P2437",
      "n1": "Bezrobotni zarejestrowani",
      "measureUnitName": "osoba"
    }
  ]
}
"""

GUS_DBW_CPI_JSON = """
{
  "page": 1,
  "page-size": 10,
  "total-records": 1,
  "data": [
    {
      "id-zmienna": 305,
      "id-przekroj": 736,
      "id-rok": 2026,
      "id-okres": 255,
      "wartosc": 104.2,
      "precyzja": 1
    }
  ]
}
"""


# ==============================================================================
# TESTY NBP CONNECTOR
# ==============================================================================

class TestNbpConnector:
    """Testy oficjalnego konektora NBP (REST i XML)."""

    def test_fetch_eur_rate_success(self):
        connector = NbpConnector(offline_mode=True)
        connector.register_fixture("rates/A/EUR", NBP_EUR_JSON)

        evidence, obs = connector.fetch_exchange_rate("EUR")

        assert evidence.source_id == "SRC_NBP"
        assert evidence.document_type == "API_RESPONSE"
        assert evidence.status_code == 200
        assert len(evidence.content_hash) == 64

        assert obs.indicator_code == "PL_FX_EUR_PLN"
        assert obs.country_code == "PL"
        assert obs.period_start == "2026-10-30"
        assert obs.period_end == "2026-10-30"
        assert obs.frequency == "DAILY"
        assert obs.value_decimal == "4.345"
        assert obs.unit_code == "EUR_PLN"
        assert obs.revision_type == "FINAL"
        assert obs.status == "VERIFIED"
        assert obs.evidence_id == evidence.evidence_id
        assert obs.metadata["table_no"] == "212/A/NBP/2026"

    def test_fetch_usd_rate_success(self):
        connector = NbpConnector(offline_mode=True)
        connector.register_fixture("rates/A/USD", NBP_USD_JSON)

        evidence, obs = connector.fetch_exchange_rate("usd")

        assert obs.indicator_code == "PL_FX_USD_PLN"
        assert obs.value_decimal == "4.0215"
        assert obs.unit_code == "USD_PLN"

    def test_fetch_reference_rate_xml_success(self):
        connector = NbpConnector(offline_mode=True)
        connector.register_fixture("stopy_procentowe.xml", NBP_RATES_XML)

        evidence, obs = connector.fetch_reference_rate()

        assert evidence.source_id == "SRC_NBP"
        assert evidence.document_type == "OFFICIAL_XML"
        assert obs.indicator_code == "PL_NBP_REFERENCE_RATE"
        assert obs.period_start == "2023-10-05"
        assert obs.period_end == "2023-10-05"
        assert obs.frequency == "IRREGULAR"
        assert obs.value_decimal == "5.75"
        assert obs.unit_code == "PCT"
        assert obs.status == "VERIFIED"
        assert obs.metadata["rate_type"] == "referencyjna"

    def test_unsupported_currency_raises_validation_error(self):
        connector = NbpConnector(offline_mode=True)
        with pytest.raises(ValidationError, match="Nieobsługiwany kod waluty"):
            connector.fetch_exchange_rate("GBP")

    def test_empty_rates_raises_data_not_found(self):
        connector = NbpConnector(offline_mode=True)
        empty_json = json.dumps({"table": "A", "currency": "euro", "code": "EUR", "rates": []})
        connector.register_fixture("rates/A/EUR", empty_json)

        with pytest.raises(DataNotFoundError, match="Brak notowań dla waluty"):
            connector.fetch_exchange_rate("EUR")

    def test_malformed_xml_raises_validation_error(self):
        connector = NbpConnector(offline_mode=True)
        connector.register_fixture("stopy_procentowe.xml", "<not_closed_xml")

        with pytest.raises(ValidationError, match="Błąd parsowania XML"):
            connector.fetch_reference_rate()


# ==============================================================================
# TESTY EUROSTAT CONNECTOR (W TYM TEICP000, ARCHIWALNY HICP ORAZ FRESHNESS GUARD)
# ==============================================================================

class TestEurostatConnector:
    """Testy oficjalnego konektora Eurostatu (JSON-stat 2.0)."""

    def test_fetch_hicp_teicp000_coicop_2018_default_success(self):
        """Weryfikuje pobieranie aktualnej serii HICP z tabeli teicp000 (COICOP 2018, dane z 2026 r.)."""
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("teicp000", EUROSTAT_TEICP000_JSON)

        evidence, observations = connector.fetch_hicp("PL", dataset="teicp000", require_fresh=True)

        assert evidence.source_id == "SRC_EUROSTAT"
        assert len(observations) == 3

        latest = observations[-1]
        assert latest.indicator_code == "EU_HICP_YOY"
        assert latest.country_code == "PL"
        assert latest.period_start == "2026-09-01"
        assert latest.period_end == "2026-09-30"
        assert latest.frequency == "MONTHLY"
        assert latest.value_decimal == "4.0"
        assert latest.unit_code == "PCT"
        assert latest.status == "VERIFIED"
        assert latest.publication_date is None
        assert latest.metadata["dataset"] == "teicp000"
        assert latest.metadata["classification"] == "COICOP_2018"
        assert latest.metadata["is_archival"] is False
        assert latest.metadata["completeness_pct"] == 100.0

    def test_fetch_hicp_archival_prc_hicp_manr_success(self):
        """Weryfikuje pobieranie archiwalnej serii HICP z prc_hicp_manr (COICOP 1999)."""
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("prc_hicp_manr", EUROSTAT_HICP_ARCHIVAL_2025_JSON)

        evidence, observations = connector.fetch_hicp_archival("PL")

        assert len(observations) == 3
        latest = observations[-1]
        assert latest.indicator_code == "EU_HICP_YOY"
        assert latest.period_end == "2025-12-31"
        assert latest.value_decimal == "2.5"
        assert latest.metadata["dataset"] == "prc_hicp_manr"
        assert latest.metadata["classification"] == "COICOP_1999_ARCHIVAL"
        assert latest.metadata["is_archival"] is True

    def test_hicp_freshness_guard_blocks_2025_reading_in_2026(self):
        """
        Kluczowy test świeżości danych (Wymóg 1):
        Nie dopuszcza do prezentowania ostatniego odczytu z 2025 r. jako aktualnego w 2026 r.
        Gdy żądana jest świeża seria (require_fresh=True) lub sprawdzany jest szereg archiwalny,
        system musi zgłosić StaleDataError.
        """
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("prc_hicp_manr", EUROSTAT_HICP_ARCHIVAL_2025_JSON)
        connector.register_fixture("teicp000", EUROSTAT_TEICP000_JSON)

        # 1. Próba pobrania serii z 2025 r. jako aktualnej z wymogiem świeżości rzuca StaleDataError
        with pytest.raises(StaleDataError, match="Brak świeżości danych"):
            connector.fetch_hicp("PL", dataset="prc_hicp_manr", require_fresh=True)

        # 2. Bezpośrednia weryfikacja świeżości na liście obserwacji z 2025 r.
        _, obs_archival = connector.fetch_hicp_archival("PL")
        with pytest.raises(StaleDataError, match="pochodzi z roku 2025"):
            connector.validate_series_freshness(obs_archival, reference_year=2026)

        # 3. Seria z teicp000 (2026 r.) przechodzi pomyślnie walidację świeżości
        _, obs_fresh = connector.fetch_hicp("PL", dataset="teicp000", require_fresh=True)
        assert connector.validate_series_freshness(obs_fresh, reference_year=2026) is True

    def test_fetch_hicp_backward_compatibility_fallback(self):
        """Weryfikuje kompatybilność wsteczną dla starszych fixture prc_hicp_manr."""
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("prc_hicp_manr", EUROSTAT_HICP_JSON)

        evidence, observations = connector.fetch_hicp("PL")
        assert len(observations) == 3
        assert observations[0].indicator_code == "EU_HICP_YOY"
        assert observations[0].value_decimal == "4.2"

    def test_fetch_harmonized_unemployment_success(self):
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("une_rt_m", EUROSTAT_UNEMPLOYMENT_JSON)

        evidence, observations = connector.fetch_harmonized_unemployment("PL")

        assert len(observations) == 2
        obs = observations[1]
        assert obs.indicator_code == "PL_UNEMPLOYMENT_LFS_RATE"
        assert obs.period_start == "2026-09-01"
        assert obs.period_end == "2026-09-30"
        assert obs.value_decimal == "2.9"
        assert obs.unit_code == "PCT"
        assert obs.metadata["standard"] == "ILO_BAEL"
        assert obs.publication_date is None

    def test_fetch_quarterly_gdp_growth_qoq_success(self):
        """Weryfikuje, że dynamika kw/kw (PCH_PRE) jest poprawnie oznaczana jako PL_GDP_QOQ z jednostką PCT."""
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("unit=PCH_PRE", EUROSTAT_GDP_GROWTH_QOQ_JSON)

        evidence, observations = connector.fetch_quarterly_gdp("PL", measure="GROWTH_QOQ")

        assert len(observations) == 2
        q1 = observations[0]
        assert q1.indicator_code == "PL_GDP_QOQ"
        assert q1.period_start == "2026-01-01"
        assert q1.period_end == "2026-03-31"
        assert q1.frequency == "QUARTERLY"
        assert q1.value_decimal == "0.8"
        assert q1.unit_code == "PCT"
        assert q1.metadata["eurostat_unit"] == "PCH_PRE"
        assert q1.publication_date is None

        q2 = observations[1]
        assert q2.indicator_code == "PL_GDP_QOQ"
        assert q2.period_start == "2026-04-01"
        assert q2.period_end == "2026-06-30"
        assert q2.value_decimal == "1.1"
        assert q2.unit_code == "PCT"

    def test_fetch_quarterly_gdp_growth_yoy_success(self):
        """Weryfikuje, że dynamika r/r (PCH_SM_PR_Y) jest poprawnie oznaczana jako PL_GDP_YOY z jednostką PCT."""
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("unit=PCH_SM_PR_Y", EUROSTAT_GDP_GROWTH_YOY_JSON)

        evidence, observations = connector.fetch_quarterly_gdp("PL", measure="GROWTH_YOY")

        assert len(observations) == 2
        assert observations[0].indicator_code == "PL_GDP_YOY"
        assert observations[0].value_decimal == "3.4"
        assert observations[0].unit_code == "PCT"

    def test_fetch_quarterly_gdp_volume_separated_from_qoq(self):
        """
        Kluczowy test regresyjny (Problem 1 z Code Review):
        Poziom/wolumen PKB (CLV10_MEUR) NIE MOŻE być zapisywany jako PL_GDP_QOQ ani jako punkty indeksowe!
        Musi mieć kod wskaźnika PL_GDP_VOLUME oraz jednostkę MEUR.
        """
        connector = EurostatConnector(offline_mode=True)
        connector.register_fixture("unit=CLV10_MEUR", EUROSTAT_GDP_VOLUME_JSON)

        evidence, observations = connector.fetch_quarterly_gdp("PL", measure="VOLUME_MEUR")

        assert len(observations) == 2
        q1 = observations[0]
        # Potwierdzenie rozdzielenia definicji i jednostek
        assert q1.indicator_code == "PL_GDP_VOLUME"
        assert q1.indicator_code != "PL_GDP_QOQ"
        assert q1.unit_code == "MEUR"
        assert q1.unit_code != "INDEX_POINTS"
        assert q1.value_decimal == "135400.5"
        assert q1.publication_date is None

        q2 = observations[1]
        assert q2.indicator_code == "PL_GDP_VOLUME"
        assert q2.unit_code == "MEUR"
        assert q2.value_decimal == "136850.2"

    def test_invalid_gdp_measure_raises_validation_error(self):
        connector = EurostatConnector(offline_mode=True)
        with pytest.raises(ValidationError, match="Nieobsługiwana miara PKB"):
            connector.fetch_quarterly_gdp("PL", measure="INVALID_MEASURE")

    def test_missing_time_dimension_raises_validation_error(self):
        connector = EurostatConnector(offline_mode=True)
        bad_json = json.dumps({"version": "2.0", "dimension": {}})
        connector.register_fixture("prc_hicp_manr", bad_json)

        with pytest.raises(ValidationError, match="Brak wymiaru 'time'"):
            connector.fetch_hicp("PL")

    def test_multidimensional_jsonstat_parser_and_completeness_control(self):
        """
        Weryfikuje poprawność wielowymiarowego parsera JSON-stat 2.0 z kalkulacją strides:
        - poprawny iloczyn wymiarów stride[i] = stride[i+1] * size[i+1]
        - precyzyjne adresowanie w spłaszczonej tablicy wartości (flat_index = sum(coord * stride))
        - kontrola kompletności danych (total_periods, valid_periods, missing_periods, completeness_pct)
        - odporność na brakujące okresy
        """
        connector = EurostatConnector(offline_mode=True)
        # Przykładowa kostka 3D: [geo (2), unit (2), time (3)]
        # size: [2, 2, 3] -> strides: time=1, unit=3, geo=6, total=12
        cube = {
            "version": "2.0",
            "class": "dataset",
            "id": ["geo", "unit", "time"],
            "size": [2, 2, 3],
            "dimension": {
                "geo": {"category": {"index": {"DE": 0, "PL": 1}}},
                "unit": {"category": {"index": {"PCH_PRE": 0, "CLV10_MEUR": 1}}},
                "time": {"category": {"index": {"2026Q1": 0, "2026Q2": 1, "2026Q3": 2}}},
            },
            # Dla PL (geo=1 -> base=6), unit=PCH_PRE (unit=0 -> offset=0) -> indeksy bazowe: 6 + 0 + t = 6, 7, 8
            # Dla PL (geo=1), unit=CLV10_MEUR (unit=1 -> offset=3) -> indeksy bazowe: 6 + 3 + t = 9, 10, 11
            # Celowo pomijamy 2026Q2 dla PL PCH_PRE (indeks 7), aby przetestować missing_periods i completeness
            "value": {
                "0": 0.2, "1": 0.3, "2": 0.4,
                "6": 0.8, "8": 1.2,
                "9": 100.0, "10": 105.0, "11": 110.0,
            },
        }

        # Test wyodrębnienia PL PCH_PRE z brakującą obserwacją
        series_pch, metrics_pch = connector._extract_jsonstat_time_series(
            cube, target_categories={"geo": "PL", "unit": "PCH_PRE"}
        )
        assert len(series_pch) == 2
        assert series_pch[0] == ("2026Q1", 0.8)
        assert series_pch[1] == ("2026Q3", 1.2)
        assert metrics_pch["total_periods"] == 3
        assert metrics_pch["valid_periods"] == 2
        assert metrics_pch["missing_periods"] == 1
        assert metrics_pch["completeness_pct"] == 66.67
        assert metrics_pch["resolved_coords"] == {"geo": 1, "unit": 0}

        # Test wyodrębnienia PL CLV10_MEUR z pełną serią 100%
        series_clv, metrics_clv = connector._extract_jsonstat_time_series(
            cube, target_categories={"geo": "PL", "unit": "CLV10_MEUR"}
        )
        assert len(series_clv) == 3
        assert [v for _, v in series_clv] == [100.0, 105.0, 110.0]
        assert metrics_clv["completeness_pct"] == 100.0
        assert metrics_clv["missing_periods"] == 0


# ==============================================================================
# TESTY GUS CONNECTOR (W TYM POPRAWKI OKRESU, PRZELICZENIA CPI ORAZ MAPPING GUARDS)
# ==============================================================================

class TestGusConnector:
    """Testy oficjalnego konektora GUS (BDL i DBW)."""

    def test_fetch_registered_unemployment_bdl_success(self):
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("by-variable/60270", GUS_BDL_UNEMPLOYMENT_JSON)

        evidence, observations = connector.fetch_registered_unemployment()

        assert evidence.source_id == "SRC_GUS_BDL"
        assert len(observations) == 2

        obs_ann = observations[0]
        assert obs_ann.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_RATE"
        assert obs_ann.period_start == "2025-01-01"
        assert obs_ann.period_end == "2025-12-31"
        assert obs_ann.frequency == "ANNUAL"
        assert obs_ann.value_decimal == "5.1"
        assert obs_ann.unit_code == "PCT"
        assert obs_ann.status == "VERIFIED"
        assert obs_ann.publication_date is None

        obs_month = observations[1]
        assert obs_month.period_start == "2026-08-01"
        assert obs_month.period_end == "2026-08-31"
        assert obs_month.frequency == "MONTHLY"
        assert obs_month.value_decimal == "5.0"
        assert obs_month.publication_date is None

    def test_fetch_registered_unemployment_count_blocks_unmapped_call(self):
        """Wywołanie bez argumentów rzuca VariableNotMappedError."""
        connector = GusConnector(offline_mode=True)
        with pytest.raises(VariableNotMappedError, match="status NOT_VERIFIED"):
            connector.fetch_registered_unemployment_count()

    def test_fetch_registered_unemployment_count_arbitrary_var_id_remains_not_verified(self):
        """
        Kluczowy test rygoru walidacji (Wymóg 2):
        Samo podanie dowolnego var_id (np. 60269) bez zweryfikowanego mapowania
        NIE oznacza zmiennej jako VERIFIED — musi mieć status NOT_VERIFIED!
        """
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("by-variable/60269", GUS_BDL_COUNT_JSON)

        evidence, observations = connector.fetch_registered_unemployment_count(var_id=60269)

        assert len(observations) == 1
        obs = observations[0]
        assert obs.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_COUNT"
        assert obs.value_decimal == "845.3"
        # Rygor: status musi być NOT_VERIFIED!
        assert obs.status == "NOT_VERIFIED"
        assert obs.status != "VERIFIED"
        assert obs.metadata["status_reason"] in ("UNVERIFIED_VARIABLE_MAPPING", "VARIABLE_NOT_FOUND_IN_OFFICIAL_GUS_API")

    def test_fetch_registered_unemployment_count_incomplete_mapping_raises_validation_error(self):
        """Przekazanie niekompletnego mapowania (np. bez częstotliwości) rzuca ValidationError."""
        connector = GusConnector(offline_mode=True)
        incomplete_mapping = {
            "var_id": 999999,
            "name": "Bezrobotni zarejestrowani",
            "unit_code": "THOUSAND_PERSONS",
            # brak pola frequency
        }
        with pytest.raises(ValidationError, match="Niekompletne mapowanie"):
            connector.fetch_registered_unemployment_count(verified_mapping=incomplete_mapping)

    def test_fetch_registered_unemployment_count_fictitious_mapping_cannot_grant_verified(self):
        """
        Kluczowy test bezpieczeństwa danych:
        Kompletny, ale fikcyjny słownik metadanych przekazany przez wywołującego
        NIE MOŻE nadać statusu VERIFIED.
        Status musi pozostać NOT_VERIFIED (lub PENDING), dopóki nie zostanie zweryfikowany
        w oficjalnych metadanych GUS API lub osobnym rejestrze zatwierdzonych mapowań.
        """
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("by-variable/999999", GUS_BDL_COUNT_JSON)

        fictitious_mapping = {
            "var_id": 999999,
            "name": "Fikcyjna liczba bezrobotnych zarejestrowanych",
            "unit_code": "THOUSAND_PERSONS",
            "frequency": "MONTHLY",
        }

        evidence, observations = connector.fetch_registered_unemployment_count(verified_mapping=fictitious_mapping)

        assert len(observations) == 1
        obs = observations[0]
        assert obs.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_COUNT"
        # Rygor bezpieczeństwa danych: status NIE MOŻE być VERIFIED!
        assert obs.status == "NOT_VERIFIED"
        assert obs.status != "VERIFIED"
        assert "VARIABLE_NOT_FOUND_IN_OFFICIAL_GUS_API" in obs.metadata["status_reason"]

    def test_fetch_registered_unemployment_count_preapproved_registry_succeeds_as_verified(self):
        """
        Wskaźnik znajdujący się w osobnym, wcześniej zatwierdzonym rejestrze mapowań
        (APPROVED_BDL_REGISTRY) uzyskuje status VERIFIED.
        """
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("by-variable/777777", GUS_BDL_COUNT_JSON)
        connector.APPROVED_BDL_REGISTRY[777777] = {
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_COUNT",
            "name": "Liczba bezrobotnych zarejestrowanych (zatwierdzony rejestr)",
            "unit_code": "THOUSAND_PERSONS",
            "frequency": "MONTHLY",
            "status": "VERIFIED",
        }

        evidence, observations = connector.fetch_registered_unemployment_count(var_id=777777)

        assert len(observations) == 1
        obs = observations[0]
        assert obs.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_COUNT"
        assert obs.status == "VERIFIED"
        assert obs.unit_code == "THOUSAND_PERSONS"
        assert obs.metadata["status_reason"] == "VERIFIED_PREAPPROVED_REGISTRY"

    def test_fetch_registered_unemployment_count_verified_via_official_gus_api_metadata(self):
        """
        Gdy identyfikator, definicja, jednostka i częstotliwość zostaną potwierdzone
        w rzeczywistych metadanych oficjalnego API GUS (GET /variables/{id}),
        obserwacja uzyskuje status VERIFIED.
        """
        connector = GusConnector(offline_mode=True)
        gus_var_meta = json.dumps({
            "id": 888888,
            "subjectId": "P2437",
            "n1": "Liczba zarejestrowanych bezrobotnych",
            "level": 3,
            "measureUnitName": "tys. osób",
        })
        connector.register_fixture("variables/888888", gus_var_meta)
        connector.register_fixture("by-variable/888888", GUS_BDL_COUNT_JSON)

        valid_candidate_mapping = {
            "var_id": 888888,
            "name": "Liczba zarejestrowanych bezrobotnych",
            "unit_code": "THOUSAND_PERSONS",
            "frequency": "MONTHLY",
        }

        evidence, observations = connector.fetch_registered_unemployment_count(candidate_mapping=valid_candidate_mapping)

        assert len(observations) == 1
        obs = observations[0]
        assert obs.indicator_code == "PL_UNEMPLOYMENT_REGISTERED_COUNT"
        assert obs.status == "VERIFIED"
        assert obs.unit_code == "THOUSAND_PERSONS"
        assert obs.metadata["status_reason"] == "VERIFIED_OFFICIAL_API_METADATA"

    def test_fetch_cpi_dbw_resolves_exact_month_from_period_metadata(self):
        """
        Kluczowy test regresyjny (Problem 2 z Code Review):
        Miesięczna obserwacja CPI z DBW (okres_id 255 = wrzesień) NIE MOŻE mieć zakresu 01-01 do 12-31!
        Musi mieć okres od 2026-09-01 do 2026-09-30.
        Rozdzielenie period_end od publication_date (publication_date=None).
        """
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("data/data-data", GUS_DBW_CPI_JSON)

        evidence, obs = connector.fetch_cpi_dbw(rok=2026, okres_id=255)

        assert evidence.source_id == "SRC_GUS_DBW"
        assert obs.indicator_code == "PL_CPI_YOY"
        assert obs.period_start == "2026-09-01"
        assert obs.period_end == "2026-09-30"
        assert obs.publication_date is None
        assert obs.metadata["resolved_month"] == 9

    def test_fetch_cpi_dbw_with_explicit_month(self):
        """Weryfikuje poprawne działanie z jawnym parametrem month."""
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("data/data-data", GUS_DBW_CPI_JSON)

        evidence, obs = connector.fetch_cpi_dbw(rok=2026, okres_id=9, month=9)
        assert obs.period_start == "2026-09-01"
        assert obs.period_end == "2026-09-30"

    def test_fetch_cpi_dbw_unresolvable_period_raises_error(self):
        """Gdy okres_id jest nieznany i brak parametru month, konektor zgłasza błąd zamiast zgadywać."""
        connector = GusConnector(offline_mode=True)
        with pytest.raises(ValidationError, match="Nie można jednoznacznie ustalić miesiąca"):
            connector.fetch_cpi_dbw(rok=2026, okres_id=999)

    def test_fetch_cpi_dbw_methodological_conversion_without_heuristic(self):
        """
        Kluczowy test regresyjny (Problem 3 z Code Review):
        Brak heurystyki 'wartosc > 50'. Konwersja opiera się na potwierdzonej metodologii:
        - Dla is_index_base_100=True: 104.2 przeliczane na 4.2% r/r.
        - Dla as_percentage_change=False: zachowywany jest surowy indeks 104.2 jako INDEX_POINTS.
        - Dla is_index_base_100=False: wartość nie jest modyfikowana arytmetycznie.
        """
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("data/data-data", GUS_DBW_CPI_JSON)

        # 1. Domyślna konwersja metodologiczna bazy 100 do stopy r/r
        _, obs_pct = connector.fetch_cpi_dbw(rok=2026, okres_id=255, is_index_base_100=True, as_percentage_change=True)
        assert obs_pct.value_decimal == "4.2"
        assert obs_pct.unit_code == "PCT"

        # 2. Pobranie jako surowy punkt indeksu (bez odejmowania 100)
        _, obs_idx = connector.fetch_cpi_dbw(rok=2026, okres_id=255, is_index_base_100=True, as_percentage_change=False)
        assert obs_idx.value_decimal == "104.2"
        assert obs_idx.unit_code == "INDEX_POINTS"

        # 3. Seria, która nie jest bazą 100 (brak odejmowania 100)
        low_val_json = json.dumps({"data": [{"id-zmienna": 305, "id-przekroj": 736, "wartosc": 3.4}]})
        connector.register_fixture("data/data-data", low_val_json)
        _, obs_direct = connector.fetch_cpi_dbw(rok=2026, okres_id=255, is_index_base_100=False, as_percentage_change=True)
        assert obs_direct.value_decimal == "3.4"
        assert obs_direct.unit_code == "PCT"

    def test_search_bdl_variables_success(self):
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("variables/search", GUS_BDL_SEARCH_JSON)

        results = connector.search_bdl_variables("bezrobocie")

        assert len(results) == 2
        assert results[0]["id"] == 60270
        assert results[1]["id"] == 60269

    def test_strict_anti_hallucination_unmapped_indicator_raises_error(self):
        """Wskaźnik bez potwierdzonego ID (np. wynagrodzenia) nie może używać zmyślonego ID."""
        connector = GusConnector(offline_mode=True)

        with pytest.raises(VariableNotMappedError, match="status CONFIRMED_API_REQUIRES_VARIABLE_MAPPING"):
            connector.fetch_indicator("PL_WAGE_AVERAGE_GROSS")

        with pytest.raises(VariableNotMappedError, match="status CONFIRMED_API_REQUIRES_VARIABLE_MAPPING"):
            connector.fetch_indicator("PL_INDUSTRIAL_PRODUCTION_YOY")

    def test_unmapped_indicator_with_explicit_verified_var_id_succeeds(self):
        """Jeśli użytkownik przekaże ID, pobranie się powiedzie ze statusem NOT_VERIFIED dopóki brak pełnego mapowania."""
        connector = GusConnector(offline_mode=True)
        connector.register_fixture("by-variable/644070", GUS_BDL_COUNT_JSON)

        evidence, observations = connector.fetch_indicator(
            "PL_WAGE_AVERAGE_GROSS", var_id=644070, unit_code="PLN_PER_MONTH"
        )

        assert observations[0].indicator_code == "PL_WAGE_AVERAGE_GROSS"
        assert observations[0].unit_code == "PLN_PER_MONTH"
        assert observations[0].status == "NOT_VERIFIED"


# ==============================================================================
# TESTY BAZOWE: BASE CONNECTOR (WALIDACJA, BEZPIECZEŃSTWO, ODPORNOŚĆ)
# ==============================================================================

class TestBaseConnectorGuards:
    """Testy mechanizmów walidacyjnych i odpornościowych BaseConnector."""

    def test_offline_mode_blocks_unmocked_calls(self):
        connector = BaseConnector(offline_mode=True)
        with pytest.raises(ConnectorException, match="Tryb offline aktywny, brak zarejestrowanego fixture"):
            connector._execute_request("https://api.stat.gov.pl/test")

    def test_validate_value_handles_comma_and_spaces(self):
        connector = BaseConnector()
        assert connector.validate_value(" 1 234,56 % ") == "1234.56"
        assert connector.validate_value(Decimal("5.75")) == "5.75"
        assert connector.validate_value(100) == "100"

    def test_validate_value_range_checks(self):
        connector = BaseConnector()
        with pytest.raises(ValidationError, match="poniżej dopuszczalnego minimum"):
            connector.validate_value("-5.0", min_plausible=Decimal("0.0"))

        with pytest.raises(ValidationError, match="przekracza dopuszczalne maksimum"):
            connector.validate_value("150.0", max_plausible=Decimal("100.0"))

    def test_validate_iso_date(self):
        connector = BaseConnector()
        assert connector.validate_iso_date("2026-10-31") == "2026-10-31"

        with pytest.raises(ValidationError, match="Nieprawidłowy format daty ISO"):
            connector.validate_iso_date("31-10-2026")

        with pytest.raises(ValidationError, match="Data nie może być pusta"):
            connector.validate_iso_date("")

    def test_validate_frequency_and_unit(self):
        connector = BaseConnector()
        assert connector.validate_frequency("monthly") == "MONTHLY"
        with pytest.raises(ValidationError, match="Nieznana częstotliwość"):
            connector.validate_frequency("BIWEEKLY")

        assert connector.validate_unit("pct") == "PCT"
        assert connector.validate_unit("meur") == "MEUR"
        with pytest.raises(ValidationError, match="Nieznana jednostka"):
            connector.validate_unit("APPLES")

    def test_create_evidence_has_sha256_and_unique_id(self):
        connector = BaseConnector()
        evi = connector.create_evidence(
            source_id="SRC_TEST",
            source_url="https://test.example.com",
            document_type="TEST_DOC",
            payload_text="Sample payload",
            content_hash="abc123hash",
            status_code=200,
            retrieved_at_utc="2026-11-02T12:00:00Z",
        )
        assert evi.evidence_id.startswith("EVI_")
        assert evi.to_dict()["source_id"] == "SRC_TEST"
