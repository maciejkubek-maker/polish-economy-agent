"""
Zestaw testów systemowej naprawy walidatora wskaźników i przypisów (TASK: FINAL LIVE VALIDATOR REPAIR).
Plik: tests/test_systemic_validator.py

Pokrywa:
1. Odtworzenie i naprawa błędu z przebiegu RUN_335b110450f8 (stopa bezrobocia BAEL/LFS 3.4%).
2. Pełną macierz testów Etapu 3:
   - BAEL/LFS 3.4% z prawidłowym przypisem (PASS)
   - Ogólna „stopa bezrobocia” z prawidłowym przypisem LFS (PASS)
   - Bezrobocie rejestrowane 5.8% z poprawnym źródłem GUS (PASS)
   - Tekst „rejestrowane”, przypis LFS (FAIL)
   - Tekst „BAEL”, przypis rejestrowane (FAIL)
   - CPI i HICP identyczna wartość, zamienione przypisy (FAIL)
   - PKB PL i EU identyczna wartość, zamienione przypisy (FAIL)
   - Dwie różne liczby z dwoma różnymi przypisami w jednym zdaniu (PASS)
   - Liczba nieistniejąca w VERIFIED observations (FAIL)
   - Poprawna liczba, lecz błędny okres, jednostka lub observation_id (FAIL)
   - Niepoprawny JSON GPT (FAIL)
   - Błąd GPT API (FAIL, brak fallbacku)
3. Izolację przebiegów (brak kontaminacji danymi z wcześniejszych run_id).
4. Bezpieczną kwarantannę danych geograficznych w current_observations bez naruszenia append-only w observations.
5. Pełny przebieg E2E w trybie offline ze wszystkimi wskaźnikami makro i weryfikacją we Flasku.
"""

from datetime import datetime, timezone
import json
import os
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Tuple
import pytest

import config
from app import server, set_db, set_storage_v2
from modules.connectors.base import MacroObservation, RawEvidence
from modules.evaluator import EconomyEvaluator
from modules.pipeline_v2 import MacroPipelineV2
from modules.storage_v2 import SQLiteV2Storage


# ==============================================================================
# POMOCNICZE GENERATORY DANYCH TESTOWYCH I WALIDACJI
# ==============================================================================

def _make_evidence_and_obs(
    code: str,
    val: str,
    country_code: str = "PL",
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
    unit: str = "PCT",
    source_id: str = "SRC_GUS",
    url: str = "",
    status: str = "VERIFIED",
    run_id: str = "RUN_TEST",
) -> Tuple[RawEvidence, MacroObservation]:
    token = uuid.uuid4().hex[:8]
    evi = RawEvidence(
        evidence_id=f"EVI_{code}_{token}",
        source_id=source_id,
        source_url=url or f"https://stat.gov.pl/{code.lower()}_{token}",
        document_type="API_RESPONSE",
        content_hash=f"hash_{code}_{token}",
        payload_text=f"Official data for {code}: {val}",
        status_code=200,
        retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    obs = MacroObservation(
        observation_id=f"OBS_{code}_{token}",
        indicator_code=code,
        country_code=country_code,
        period_start=period_start,
        period_end=period_end,
        frequency="MONTHLY" if len(period_start) == 10 and period_start.endswith("-01") and period_end.endswith(("-28", "-30", "-31")) else "QUARTERLY",
        value_decimal=val,
        unit_code=unit,
        revision_type="FINAL",
        status=status,
        evidence_id=evi.evidence_id,
    )
    return evi, obs


def _setup_test_db(tmp_path, name: str = "test.db") -> SQLiteV2Storage:
    db_path = str(tmp_path / name)
    storage = SQLiteV2Storage(db_path=db_path)
    return storage


def _run_validation(
    evaluator: EconomyEvaluator,
    candidate_payload: Any,
    citations: List[Dict[str, Any]],
    verified_obs: List[Dict[str, Any]],
    run_id: str = "RUN_TEST",
) -> Dict[str, Any]:
    """Pomocniczy parser i walidator odzwierciedlający produkcyjną ścieżkę evaluate_from_v2."""
    parsed = evaluator._parse_candidate_payload(
        candidate=candidate_payload,
        citations=citations,
        verified_obs=verified_obs,
        require_json=True,
    )
    evaluator._validate_structured_report(
        structured_data=parsed,
        citations=citations,
        verified_obs=verified_obs,
        run_id=run_id,
    )
    return parsed


# ==============================================================================
# ETAP 1 & 2: ODTWORZENIE I WERYFIKACJA NAPRAWY RUN_335b110450f8
# ==============================================================================

def test_run_335b110450f8_lfs_unemployment_reproduction_passes():
    """Weryfikuje, że rzeczywisty scenariusz RUN_335b110450f8:
    - Oficjalna obserwacja PL_UNEMPLOYMENT_LFS_RATE = 3.4% [9]
    - Tekst GPT: 'stopa bezrobocia BAEL/LFS wyniosła 3.4% [9]'
    nie jest już fałszywie klasyfikowany jako PL_UNEMPLOYMENT_REGISTERED_RATE i przechodzi walidację.
    """
    evaluator = EconomyEvaluator()

    # Stan bazy odzwierciedlający dokładnie RUN_335b110450f8
    verified_obs = [
        {
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "observation_id": "OBS_API_62947663cda6",
            "value_decimal": "3.4",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "source_id": "SRC_EUROSTAT",
            "institution": "Eurostat",
            "country_code": "PL",
        }
    ]

    candidate_json = {
        "claims": [
            {
                "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
                "observation_id": "OBS_API_62947663cda6",
                "value_decimal": "3.4",
                "unit_code": "PCT",
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
                "citation_idx": 9,
            }
        ],
        "sections": {
            "1": "Według najnowszych danych stopa bezrobocia BAEL/LFS wyniosła 3.4% [9].",
            "2": "Sytuacja na rynku pracy pozostaje stabilna.",
            "3": "- **Kredyty i Raty:** Bez zmian.\n- **Ceny i Zakupy:** Stabilnie.\n- **Praca i Zarobki:** Stopa bezrobocia niska.",
            "4": "Dla pracodawców oznacza to umiarkowaną presję płacową.",
            "5": "Ocena ogólna jest umiarkowanie pozytywna.",
        },
    }

    citations = [
        {
            "idx": 9,
            "observation_id": "OBS_API_62947663cda6",
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "indicator_name": "Stopa bezrobocia BAEL Polska",
            "institution": "Eurostat",
            "url": "https://ec.europa.eu/eurostat",
            "source_id": "SRC_EUROSTAT",
            "is_official": True,
            "period": "IX 2026",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "value_decimal": "3.4",
        }
    ]

    # Walidacja musi przejść bez wyjątku
    parsed = _run_validation(
        evaluator=evaluator,
        candidate_payload=json.dumps(candidate_json),
        citations=citations,
        verified_obs=verified_obs,
        run_id="RUN_335b110450f8",
    )

    assert parsed["claims"][0]["indicator_code"] == "PL_UNEMPLOYMENT_LFS_RATE"
    assert parsed["claims"][0]["value_decimal"] == "3.4"
    assert "[9]" in parsed["sections"]["1"]


# ==============================================================================
# ETAP 3: MACIERZ TESTÓW REGRESYJNYCH WALIDATORA
# ==============================================================================

def test_matrix_general_unemployment_phrase_passes_with_lfs():
    """Ogólna 'stopa bezrobocia' z poprawnym przypisem LFS przechodzi bez wymuszonej zmiany metodologii."""
    evaluator = EconomyEvaluator()
    obs = [{
        "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
        "observation_id": "OBS_LFS_1",
        "value_decimal": "3.4",
        "unit_code": "PCT",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "source_id": "SRC_EUROSTAT",
        "institution": "Eurostat",
        "country_code": "PL",
    }]
    citations = [{
        "idx": 1,
        "observation_id": "OBS_LFS_1",
        "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
        "indicator_name": "Stopa bezrobocia BAEL",
        "institution": "Eurostat",
        "url": "https://ec.europa.eu/eurostat",
        "source_id": "SRC_EUROSTAT",
        "is_official": True,
        "period": "IX 2026",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "value_decimal": "3.4",
    }]
    # Tekst używa ogólnego określenia 'stopa bezrobocia'
    candidate = {
        "claims": [{
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "observation_id": "OBS_LFS_1",
            "value_decimal": "3.4",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "citation_idx": 1,
        }],
        "sections": {
            "1": "W Polsce stopa bezrobocia ukształtowała się na poziomie 3.4% [1].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    parsed = _run_validation(evaluator, json.dumps(candidate), citations, obs)
    assert parsed["claims"][0]["indicator_code"] == "PL_UNEMPLOYMENT_LFS_RATE"


def test_matrix_registered_unemployment_gus_passes():
    """Bezrobocie rejestrowane 5.8% z poprawnym źródłem GUS przechodzi."""
    evaluator = EconomyEvaluator()
    obs = [{
        "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
        "observation_id": "OBS_REG_1",
        "value_decimal": "5.8",
        "unit_code": "PCT",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "source_id": "SRC_GUS",
        "institution": "GUS",
        "country_code": "PL",
    }]
    citations = [{
        "idx": 2,
        "observation_id": "OBS_REG_1",
        "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
        "indicator_name": "Stopa bezrobocia rejestrowanego",
        "institution": "GUS",
        "url": "https://stat.gov.pl",
        "source_id": "SRC_GUS",
        "is_official": True,
        "period": "IX 2026",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "value_decimal": "5.8",
    }]
    candidate = {
        "claims": [{
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
            "observation_id": "OBS_REG_1",
            "value_decimal": "5.8",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "citation_idx": 2,
        }],
        "sections": {
            "1": "Stopa bezrobocia rejestrowanego wyniosła 5.8% [2] według urzędów pracy.",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    parsed = _run_validation(evaluator, json.dumps(candidate), citations, obs)
    assert parsed["claims"][0]["indicator_code"] == "PL_UNEMPLOYMENT_REGISTERED_RATE"


def test_matrix_registered_text_with_lfs_citation_fails():
    """Tekst mówi 'rejestrowane', ale przypis wskazuje LFS -> FAILED (sprzeczność metodologiczna)."""
    evaluator = EconomyEvaluator()
    obs = [{
        "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
        "observation_id": "OBS_LFS_1",
        "value_decimal": "3.4",
        "unit_code": "PCT",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "source_id": "SRC_EUROSTAT",
        "institution": "Eurostat",
        "country_code": "PL",
    }]
    citations = [{
        "idx": 9,
        "observation_id": "OBS_LFS_1",
        "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
        "indicator_name": "Stopa bezrobocia BAEL",
        "institution": "Eurostat",
        "url": "https://ec.europa.eu",
        "source_id": "SRC_EUROSTAT",
        "is_official": True,
        "period": "IX 2026",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "value_decimal": "3.4",
    }]
    candidate = {
        "claims": [{
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "observation_id": "OBS_LFS_1",
            "value_decimal": "3.4",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "citation_idx": 9,
        }],
        "sections": {
            "1": "Stopa bezrobocia rejestrowanego w urzędach pracy wyniosła 3.4% [9].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    with pytest.raises(ValueError, match="Niepoprawne powiązanie przypisów ze źródłami"):
        _run_validation(evaluator, json.dumps(candidate), citations, obs)


def test_matrix_bael_text_with_registered_citation_fails():
    """Tekst mówi 'BAEL', ale przypis wskazuje bezrobocie rejestrowane -> FAILED."""
    evaluator = EconomyEvaluator()
    obs = [{
        "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
        "observation_id": "OBS_REG_1",
        "value_decimal": "5.8",
        "unit_code": "PCT",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "source_id": "SRC_GUS",
        "institution": "GUS",
        "country_code": "PL",
    }]
    citations = [{
        "idx": 2,
        "observation_id": "OBS_REG_1",
        "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
        "indicator_name": "Stopa bezrobocia rejestrowanego",
        "institution": "GUS",
        "url": "https://stat.gov.pl",
        "source_id": "SRC_GUS",
        "is_official": True,
        "period": "IX 2026",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "value_decimal": "5.8",
    }]
    candidate = {
        "claims": [{
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
            "observation_id": "OBS_REG_1",
            "value_decimal": "5.8",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "citation_idx": 2,
        }],
        "sections": {
            "1": "Stopa bezrobocia BAEL wyniosła 5.8% [2].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    with pytest.raises(ValueError, match="Niepoprawne powiązanie przypisów ze źródłami"):
        _run_validation(evaluator, json.dumps(candidate), citations, obs)


def test_matrix_cpi_and_hicp_same_value_swapped_citations_fails():
    """CPI i HICP mają identyczną wartość (4.0%), lecz zamienione przypisy w treści -> FAILED."""
    evaluator = EconomyEvaluator()
    obs = [
        {
            "indicator_code": "PL_CPI_YOY",
            "observation_id": "OBS_CPI",
            "value_decimal": "4.0",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "source_id": "SRC_GUS",
            "institution": "GUS",
            "country_code": "PL",
        },
        {
            "indicator_code": "PL_HICP_YOY",
            "observation_id": "OBS_HICP",
            "value_decimal": "4.0",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "source_id": "SRC_EUROSTAT",
            "institution": "Eurostat",
            "country_code": "PL",
        },
    ]
    citations = [
        {
            "idx": 1,
            "observation_id": "OBS_CPI",
            "indicator_code": "PL_CPI_YOY",
            "indicator_name": "Inflacja CPI r/r",
            "institution": "GUS",
            "url": "https://stat.gov.pl",
            "source_id": "SRC_GUS",
            "is_official": True,
            "period": "IX 2026",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "value_decimal": "4.0",
        },
        {
            "idx": 2,
            "observation_id": "OBS_HICP",
            "indicator_code": "PL_HICP_YOY",
            "indicator_name": "Wskaźnik HICP",
            "institution": "Eurostat",
            "url": "https://ec.europa.eu",
            "source_id": "SRC_EUROSTAT",
            "is_official": True,
            "period": "IX 2026",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "value_decimal": "4.0",
        },
    ]

    # Tekst przypisuje [2] (HICP) do 'inflacja CPI'
    candidate = {
        "claims": [
            {
                "indicator_code": "PL_HICP_YOY",
                "observation_id": "OBS_HICP",
                "value_decimal": "4.0",
                "unit_code": "PCT",
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
                "citation_idx": 2,
            }
        ],
        "sections": {
            "1": "Krajowa inflacja konsumencka CPI wyniosła 4.0% [2].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    with pytest.raises(ValueError, match="Niepoprawne powiązanie przypisów ze źródłami"):
        _run_validation(evaluator, json.dumps(candidate), citations, obs)


def test_matrix_gdp_pl_and_eu_same_value_swapped_citations_fails():
    """PKB Polski i UE mają identyczną wartość (2.8%), lecz zamienione przypisy w treści -> FAILED."""
    evaluator = EconomyEvaluator()
    obs = [
        {
            "indicator_code": "PL_GDP_YOY",
            "observation_id": "OBS_GDP_PL",
            "value_decimal": "2.8",
            "unit_code": "PCT",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "source_id": "SRC_GUS",
            "institution": "GUS",
            "country_code": "PL",
        },
        {
            "indicator_code": "EU_GDP_YOY",
            "observation_id": "OBS_GDP_EU",
            "value_decimal": "2.8",
            "unit_code": "PCT",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "source_id": "SRC_EUROSTAT",
            "institution": "Eurostat",
            "country_code": "EU",
        },
    ]
    citations = [
        {
            "idx": 1,
            "observation_id": "OBS_GDP_PL",
            "indicator_code": "PL_GDP_YOY",
            "indicator_name": "Dynamika PKB r/r Polska",
            "institution": "GUS",
            "url": "https://stat.gov.pl",
            "source_id": "SRC_GUS",
            "is_official": True,
            "period": "II kw. 2026",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "value_decimal": "2.8",
        },
        {
            "idx": 2,
            "observation_id": "OBS_GDP_EU",
            "indicator_code": "EU_GDP_YOY",
            "indicator_name": "Dynamika PKB r/r UE",
            "institution": "Eurostat",
            "url": "https://ec.europa.eu",
            "source_id": "SRC_EUROSTAT",
            "is_official": True,
            "period": "II kw. 2026",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "value_decimal": "2.8",
        },
    ]

    # Tekst mówi o wzroście PKB w Polsce, lecz przypisano do [2] (wskaźnik unijny)
    candidate = {
        "claims": [
            {
                "indicator_code": "EU_GDP_YOY",
                "observation_id": "OBS_GDP_EU",
                "value_decimal": "2.8",
                "unit_code": "PCT",
                "period_start": "2026-04-01",
                "period_end": "2026-06-30",
                "citation_idx": 2,
            }
        ],
        "sections": {
            "1": "Wzrost PKB w Polsce w ujęciu rocznym wyniósł 2.8% [2].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    with pytest.raises(ValueError, match="odnosi się do Polski, lecz powiązano je ze wskaźnikiem unijnym"):
        _run_validation(evaluator, json.dumps(candidate), citations, obs)


def test_matrix_two_distinct_numbers_in_one_sentence_passes():
    """Dwie różne liczby z dwoma różnymi przypisami w jednym zdaniu przechodzą bez wzajemnego zakłócania."""
    evaluator = EconomyEvaluator()
    obs = [
        {
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "observation_id": "OBS_LFS",
            "value_decimal": "3.4",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "source_id": "SRC_EUROSTAT",
            "institution": "Eurostat",
            "country_code": "PL",
        },
        {
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
            "observation_id": "OBS_REG",
            "value_decimal": "5.8",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "source_id": "SRC_GUS",
            "institution": "GUS",
            "country_code": "PL",
        },
    ]
    citations = [
        {
            "idx": 1,
            "observation_id": "OBS_LFS",
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "indicator_name": "Stopa bezrobocia BAEL",
            "institution": "Eurostat",
            "url": "https://ec.europa.eu",
            "source_id": "SRC_EUROSTAT",
            "is_official": True,
            "period": "IX 2026",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "value_decimal": "3.4",
        },
        {
            "idx": 2,
            "observation_id": "OBS_REG",
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
            "indicator_name": "Stopa bezrobocia rejestrowanego",
            "institution": "GUS",
            "url": "https://stat.gov.pl",
            "source_id": "SRC_GUS",
            "is_official": True,
            "period": "IX 2026",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "value_decimal": "5.8",
        },
    ]

    candidate = {
        "claims": [
            {
                "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
                "observation_id": "OBS_LFS",
                "value_decimal": "3.4",
                "unit_code": "PCT",
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
                "citation_idx": 1,
            },
            {
                "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
                "observation_id": "OBS_REG",
                "value_decimal": "5.8",
                "unit_code": "PCT",
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
                "citation_idx": 2,
            },
        ],
        "sections": {
            "1": "Stopa bezrobocia BAEL wyniosła 3.4% [1], podczas gdy bezrobocie rejestrowane ukształtowało się na poziomie 5.8% [2].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    parsed = _run_validation(evaluator, json.dumps(candidate), citations, obs)
    assert len(parsed["claims"]) == 2


def test_matrix_non_existent_number_fails():
    """Liczba nieistniejąca w VERIFIED observations zostaje odrzucona."""
    evaluator = EconomyEvaluator()
    obs = [{
        "indicator_code": "PL_CPI_YOY",
        "observation_id": "OBS_CPI",
        "value_decimal": "4.9",
        "unit_code": "PCT",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "source_id": "SRC_GUS",
        "institution": "GUS",
        "country_code": "PL",
    }]
    citations = [{
        "idx": 1,
        "observation_id": "OBS_CPI",
        "indicator_code": "PL_CPI_YOY",
        "indicator_name": "Inflacja CPI r/r",
        "institution": "GUS",
        "url": "https://stat.gov.pl",
        "source_id": "SRC_GUS",
        "is_official": True,
        "period": "IX 2026",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "value_decimal": "4.9",
    }]
    # Halucynacja: 7.2%
    candidate = {
        "claims": [{
            "indicator_code": "PL_CPI_YOY",
            "observation_id": "OBS_CPI",
            "value_decimal": "7.2",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "citation_idx": 1,
        }],
        "sections": {
            "1": "Inflacja wzrosła do 7.2% [1].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    with pytest.raises(ValueError, match="Niepoprawne powiązanie przypisów ze źródłami"):
        _run_validation(evaluator, json.dumps(candidate), citations, obs)


def test_matrix_correct_number_wrong_period_or_unit_fails():
    """Poprawna liczba (3.4%), lecz błędny okres lub jednostka -> FAILED."""
    evaluator = EconomyEvaluator()
    obs = [{
        "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
        "observation_id": "OBS_LFS",
        "value_decimal": "3.4",
        "unit_code": "PCT",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "source_id": "SRC_EUROSTAT",
        "institution": "Eurostat",
        "country_code": "PL",
    }]
    citations = [{
        "idx": 1,
        "observation_id": "OBS_LFS",
        "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
        "indicator_name": "Stopa bezrobocia BAEL",
        "institution": "Eurostat",
        "url": "https://ec.europa.eu",
        "source_id": "SRC_EUROSTAT",
        "is_official": True,
        "period": "IX 2026",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "value_decimal": "3.4",
    }]

    # A. Błędny okres (2026-08-01 zamiast 2026-09-01)
    candidate_bad_period = {
        "claims": [{
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "observation_id": "OBS_LFS",
            "value_decimal": "3.4",
            "unit_code": "PCT",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "citation_idx": 1,
        }],
        "sections": {
            "1": "Stopa bezrobocia BAEL wyniosła 3.4% [1].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    with pytest.raises(ValueError, match="Niezgodność okresu"):
        _run_validation(evaluator, json.dumps(candidate_bad_period), citations, obs)

    # B. Błędna jednostka (PLN zamiast PCT)
    candidate_bad_unit = {
        "claims": [{
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "observation_id": "OBS_LFS",
            "value_decimal": "3.4",
            "unit_code": "PLN",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "citation_idx": 1,
        }],
        "sections": {
            "1": "Stopa bezrobocia BAEL wyniosła 3.4% [1].",
            "2": "Ryzyka.",
            "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }
    with pytest.raises(ValueError, match="Niezgodność jednostki"):
        _run_validation(evaluator, json.dumps(candidate_bad_unit), citations, obs)


def test_matrix_invalid_json_fails():
    """Niepoprawny JSON GPT kończy się błędem walidacji."""
    evaluator = EconomyEvaluator()
    obs = [{
        "indicator_code": "PL_CPI_YOY",
        "observation_id": "OBS_1",
        "value_decimal": "4.9",
        "unit_code": "PCT",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "source_id": "SRC_GUS",
        "institution": "GUS",
        "country_code": "PL",
    }]
    citations = [{
        "idx": 1,
        "observation_id": "OBS_1",
        "indicator_code": "PL_CPI_YOY",
        "indicator_name": "Inflacja CPI r/r",
        "institution": "GUS",
        "url": "https://stat.gov.pl",
        "source_id": "SRC_GUS",
        "is_official": True,
        "period": "IX 2026",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "value_decimal": "4.9",
    }]

    with pytest.raises(ValueError):
        _run_validation(evaluator, "INVALID { JSON ...", citations, obs)


def test_matrix_gpt_api_error_fails_without_fallback(tmp_path, monkeypatch):
    """Błąd wywołania API GPT w pipeline_v2 kończy się statusem FAILED bez włączania fallbacku deterministycznego."""
    monkeypatch.setattr(config, "OFFLINE_MODE", False)
    db = _setup_test_db(tmp_path, "gpt_err.db")
    evi, obs = _make_evidence_and_obs("PL_CPI_YOY", "4.9")

    evaluator = EconomyEvaluator()
    def mock_broken_llm(*args, **kwargs):
        raise RuntimeError("OpenAI API Connection Timeout")

    monkeypatch.setattr(evaluator, "_run_llm_synthesis", mock_broken_llm)

    diag_dir = tmp_path / "logs_err"
    pipeline = MacroPipelineV2(
        db=db,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=diag_dir,
    )
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: ([evi], [obs], [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    result = pipeline.run(country="Polska", output_html_path=str(tmp_path / "rep.html"))

    assert result.success is False
    assert result.status == "FAILED"
    with open(diag_dir / "last_run.json", "r", encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["pipeline_status"] == "FAILED"
    assert summary["generation_mode"] == "GPT_API_ERROR"
    assert "OpenAI API Connection Timeout" in summary["fallback_reason"]


# ==============================================================================
# ETAP 4: IZOLACJA PRZEBIEGÓW I PROCEDURA KWARANTANNY SQLITE
# ==============================================================================

def test_run_isolation_historical_data_not_polluting_new_run(tmp_path):
    """Weryfikuje, że get_latest_verified_observations z podanym run_id izoluje dane i nie pobiera wpisów z innego run_id."""
    db = _setup_test_db(tmp_path, "isolation.db")

    # Run 1: historyczny wpis (np. dawny EU_HICP_YOY dla PL)
    run_id1 = db.start_ingestion_run(provider="EUROSTAT_API")
    evi1, obs1 = _make_evidence_and_obs("EU_HICP_YOY", "4.5", run_id=run_id1)
    db.save_evidence(evi1, run_id=run_id1)
    db.save_observation(obs1, run_id=run_id1)

    # Run 2: nowy poprawny wpis z odrębnym run_id
    run_id2 = db.start_ingestion_run(provider="EUROSTAT_API")
    evi2, obs2 = _make_evidence_and_obs("PL_HICP_YOY", "4.0", run_id=run_id2)
    db.save_evidence(evi2, run_id=run_id2)
    db.save_observation(obs2, run_id=run_id2)

    # Zapytanie bez run_id zwraca oba wskaźniki dla PL
    all_obs = db.get_latest_verified_observations("PL", run_id=None)
    codes_all = {o["indicator_code"] for o in all_obs}
    assert "EU_HICP_YOY" in codes_all
    assert "PL_HICP_YOY" in codes_all

    # Zapytanie z filtrem run_id2 zwraca WYŁĄCZNIE obserwacje z bieżącego przebiegu
    isolated_obs = db.get_latest_verified_observations("PL", run_id=run_id2)
    codes_isolated = {o["indicator_code"] for o in isolated_obs}
    assert "PL_HICP_YOY" in codes_isolated
    assert "EU_HICP_YOY" not in codes_isolated


def test_safe_quarantine_current_observations_without_affecting_append_only(tmp_path):
    """Weryfikuje, że cleanup_mismatched_geo_current_observations():
    - Usuwa niezgodne wpisy z tabeli current_observations.
    - Zapisuje zdarzenie w quality_events.
    - Pozostawia nienaruszoną tabelę append-only observations.
    - Triggery blokują próby bezpośredniego DELETE i UPDATE na observations.
    """
    db = _setup_test_db(tmp_path, "quarantine.db")
    run_id = db.start_ingestion_run(provider="EUROSTAT_API")

    # Dodajemy obserwację z niezgodnym geo (EU_HICP_YOY dla PL)
    evi, obs = _make_evidence_and_obs("EU_HICP_YOY", "4.0", country_code="PL", run_id=run_id)
    db.save_evidence(evi, run_id=run_id)
    db.save_observation(obs, run_id=run_id)

    # Upewniamy się, że wpis istnieje w current_observations i observations
    curr_before = db.get_current_observations("PL")
    assert any(o["indicator_code"] == "EU_HICP_YOY" for o in curr_before)
    obs_count_before = db.count_table("observations")
    assert obs_count_before >= 1

    # Uruchamiamy procedurę kwarantanny
    cleaned = db.cleanup_mismatched_geo_current_observations()
    assert cleaned >= 1

    # W current_observations wpis zniknął
    curr_after = db.get_current_observations("PL")
    assert not any(o["indicator_code"] == "EU_HICP_YOY" for o in curr_after)

    # W ściśle chronionej tabeli observations wpis NADAL ISTNIEJE (append-only)
    obs_count_after = db.count_table("observations")
    assert obs_count_after == obs_count_before

    # W quality_events zarejestrowano ostrzeżenie
    conn = db.get_connection()
    events = conn.execute("SELECT * FROM quality_events WHERE rule_code = 'GEO_MISMATCH_QUARANTINE'").fetchall()
    conn.close()
    assert len(events) >= 1

    # Weryfikacja triggerów ochronnych tabeli observations
    conn = db.get_connection()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM observations WHERE indicator_code = 'EU_HICP_YOY'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE observations SET value_decimal = '9.9' WHERE indicator_code = 'EU_HICP_YOY'")
    conn.close()


# ==============================================================================
# ETAP 5: PEŁNY INTEGRACYJNY TEST OFFLINE E2E ZE WSZYSTKIMI WSKAŹNIKAMI I FLASKIEM
# ==============================================================================

def test_full_offline_e2e_all_indicators_pipeline_to_flask(tmp_path, monkeypatch):
    """Kompletny test integracyjny offline:
    1. Rejestracja 9 wskaźników makro (CPI, HICP, PKB r/r, PKB kw/kw, BAEL, Rejestrowane, Stopa NBP, EUR/PLN, USD/PLN).
    2. Symulowana synteza GPT generująca poprawny JSON z twierdzeniami i przypisami w sekcji 1.
    3. Walidacja przez EconomyEvaluator.
    4. Zapis do SQLite v2 i wygenerowanie HTML.
    5. Test klienta Flask weryfikujący renderowanie HTML, źródła, przypisy, logo i status 200.
    6. Weryfikacja, że celowo sfałszowany raport kończy się FAILED bez publikacji.
    """
    monkeypatch.setattr(config, "OFFLINE_MODE", False)
    db = _setup_test_db(tmp_path, "e2e.db")
    diag_dir = tmp_path / "e2e_logs"

    # Przygotowanie 9 oficjalnych odczytów
    obs_defs = [
        ("PL_CPI_YOY", "4.9", "PCT", "2026-09-01", "2026-09-30", "SRC_GUS", "https://stat.gov.pl/cpi"),
        ("PL_HICP_YOY", "4.0", "PCT", "2026-09-01", "2026-09-30", "SRC_EUROSTAT", "https://ec.europa.eu/hicp"),
        ("PL_GDP_YOY", "3.2", "PCT", "2026-04-01", "2026-06-30", "SRC_GUS", "https://stat.gov.pl/gdp-yoy"),
        ("PL_GDP_QOQ", "1.2", "PCT", "2026-04-01", "2026-06-30", "SRC_GUS", "https://stat.gov.pl/gdp-qoq"),
        ("PL_UNEMPLOYMENT_LFS_RATE", "3.4", "PCT", "2026-09-01", "2026-09-30", "SRC_EUROSTAT", "https://ec.europa.eu/lfs"),
        ("PL_UNEMPLOYMENT_REGISTERED_RATE", "5.8", "PCT", "2026-09-01", "2026-09-30", "SRC_GUS", "https://stat.gov.pl/unemp"),
        ("PL_POLICY_RATE_REF", "5.75", "PCT", "2026-10-01", "2026-10-31", "SRC_NBP", "https://api.nbp.pl/ref"),
        ("PL_FX_EUR_PLN", "4.3000", "EUR_PLN", "2026-10-31", "2026-10-31", "SRC_NBP", "https://api.nbp.pl/eur"),
        ("PL_FX_USD_PLN", "3.9000", "USD_PLN", "2026-10-31", "2026-10-31", "SRC_NBP", "https://api.nbp.pl/usd"),
    ]

    all_evis = []
    all_obs = []
    for code, val, unit, p_start, p_end, src, url in obs_defs:
        evi, obs = _make_evidence_and_obs(
            code=code,
            val=val,
            unit=unit,
            period_start=p_start,
            period_end=p_end,
            source_id=src,
            url=url,
        )
        all_evis.append(evi)
        all_obs.append(obs)

    evaluator = EconomyEvaluator()

    # Symulacja poprawnej odpowiedzi GPT powiązującej każdy wskaźnik z jego indeksem przypisu
    def mock_synth(country, report_date, periods_summary, chronological_context, allow_fallback=False):
        fn_map = {}
        for line in chronological_context.splitlines():
            m = re.search(r"\[(\d+)\].*indicator_code:\s*([A-Z0-9_]+)", line)
            if m:
                fn_map[m.group(2)] = int(m.group(1))

        obs_by_code = {o.indicator_code: o for o in all_obs}
        claims = []
        for code, val, unit, p_start, p_end, src, url in obs_defs:
            claims.append({
                "indicator_code": code,
                "observation_id": obs_by_code[code].observation_id,
                "value_decimal": val,
                "unit_code": unit,
                "period_start": p_start,
                "period_end": p_end,
                "citation_idx": fn_map[code],
            })

        sections = {
            "1": (
                f"W badanym okresie inflacja CPI w Polsce wyniosła 4.9% [{fn_map['PL_CPI_YOY']}], "
                f"natomiast wskaźnik HICP osiągnął 4.0% [{fn_map['PL_HICP_YOY']}]. "
                f"Dynamika PKB rok do roku wyniosła 3.2% [{fn_map['PL_GDP_YOY']}], "
                f"a w ujęciu kwartalnym PKB kw/kw wzrósł o 1.2% [{fn_map['PL_GDP_QOQ']}]. "
                f"Stopa bezrobocia BAEL wyniosła 3.4% [{fn_map['PL_UNEMPLOYMENT_LFS_RATE']}], "
                f"podczas gdy bezrobocie rejestrowane ukształtowało się na poziomie 5.8% [{fn_map['PL_UNEMPLOYMENT_REGISTERED_RATE']}]. "
                f"Stopa referencyjna NBP pozostała na poziomie 5.75% [{fn_map['PL_POLICY_RATE_REF']}]. "
                f"Średni kurs euro wyniósł 4.3000 zł [{fn_map['PL_FX_EUR_PLN']}], "
                f"a dolara 3.9000 zł [{fn_map['PL_FX_USD_PLN']}]."
            ),
            "2": "Główne ryzyka makroekonomiczne obejmują presję cenową oraz wahania na międzynarodowych rynkach walutowych.",
            "3": (
                "- **Kredyty i Raty:** Koszt obsługi rat pozostaje pod bezpośrednim wpływem poziomu stóp banku centralnego.\n"
                "- **Ceny i Zakupy:** Dynamika cen konsumpcyjnych determinuje siłę nabywczą przeciętnego koszyka dóbr.\n"
                "- **Praca i Zarobki:** Niski wskaźnik bezrobocia gwarantuje stabilne warunki na krajowym rynku zatrudnienia."
            ),
            "4": "Przedsiębiorcy muszą monitorować parametry kosztów kredytu oraz zabezpieczać rozliczenia w walutach obcych.",
            "5": "Gospodarka Polski zachowuje równowagę makroekonomiczną przy dodatnim tempie wzrostu PKB i silnym rynku pracy.",
        }

        return json.dumps({"claims": claims, "sections": sections})

    monkeypatch.setattr(evaluator, "_run_llm_synthesis", mock_synth)

    pipeline = MacroPipelineV2(
        db=db,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=diag_dir,
    )
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: (all_evis, all_obs, [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    out_html = tmp_path / "e2e_report.html"
    result = pipeline.run(country="Polska", output_html_path=str(out_html))

    # A. Sprawdzenie wyniku pipeline
    assert result.success is True
    assert result.status in ("COMPLETED", "PARTIAL")
    assert result.report_id is not None
    assert out_html.exists()

    # B. Sprawdzenie zapisu w bazie SQLite v2
    report_record = db.get_latest_report("PL")
    assert report_record is not None
    assert report_record["report_id"] == result.report_id
    assert report_record["publication_status"] == "PUBLISHED"

    # C. Sprawdzenie zawartości HTML
    html_content = out_html.read_text(encoding="utf-8")
    assert "4.9%" in html_content
    assert "4.0%" in html_content
    assert "3.2%" in html_content
    assert "1.2%" in html_content
    assert "3.4%" in html_content
    assert "5.8%" in html_content
    assert "5.75%" in html_content
    assert "4.3000" in html_content
    assert "3.9000" in html_content
    assert "GUS" in html_content
    assert "Eurostat" in html_content
    assert "NBP" in html_content

    # D. Test klienta Flask z rygorystyczną izolacją stanu globalnego i czystym last_run
    original_storage = getattr(server, "_storage_v2", None)
    original_db = getattr(server, "_db", None)
    monkeypatch.setattr("app.get_last_run_path", lambda: tmp_path / "empty_last_run.json")
    try:
        set_storage_v2(db)
        set_db(None)
        client = server.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        rendered = resp.get_data(as_text=True)
        assert "Raport Kondycji Gospodarczej" in rendered or "RAPORT KONDYCJI GOSPODARCZEJ" in rendered
        assert "3.4%" in rendered
        assert "5.8%" in rendered
    finally:
        set_storage_v2(original_storage)
        set_db(original_db)

    # E. Test odporności: Raport z fałszywą liczbą kończy się FAILED bez publikacji
    def mock_bad_synth(*args, **kwargs):
        return json.dumps({
            "claims": [{
                "indicator_code": "PL_CPI_YOY",
                "observation_id": all_obs[0].observation_id,
                "value_decimal": "99.9",
                "unit_code": "PCT",
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
                "citation_idx": 1,
            }],
            "sections": {
                "1": "Inflacja wzrosła do 99.9% [1].",
                "2": "Ryzyka.",
                "3": "- **Kredyty i Raty:** Kredyty.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
                "4": "Przedsiębiorcy.",
                "5": "Podsumowanie.",
            }
        })

    monkeypatch.setattr(evaluator, "_run_llm_synthesis", mock_bad_synth)
    bad_diag_dir = tmp_path / "bad_e2e_logs"
    bad_pipeline = MacroPipelineV2(
        db=db,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=bad_diag_dir,
    )
    monkeypatch.setattr(bad_pipeline, "fetch_official_data", lambda rid: (all_evis, all_obs, [], []))
    monkeypatch.setattr(bad_pipeline, "search_enrichment", lambda country, rid: [])

    bad_result = bad_pipeline.run(country="Polska", output_html_path=str(tmp_path / "bad_report.html"))
    assert bad_result.success is False
    assert bad_result.status == "FAILED"
    # Upewniamy się, że najnowszy opublikowany raport w bazie NIE ZOSTAŁ nadpisany fałszywym
    latest_rep = db.get_latest_report("PL")
    assert latest_rep["report_id"] == result.report_id
    assert "99.9%" not in latest_rep["report_html"]
