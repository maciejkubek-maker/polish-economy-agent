"""
Zestaw testów dla audytu bazy SQLite i naprawy walidacji realnej stopy referencyjnej.
Plik: tests/test_real_interest_rate_audit.py

Odtwarza i weryfikuje:
1. Faktyczny scenariusz awarii RUN_0ae790030b39 (NBP 3.75% [8], archiwalna CPI 2.3% [1] z XII 2025).
2. Odrzucenie prezentacji różnicy stopy NBP i archiwalnej CPI jako bieżącej realnej stopy (ARCHIVAL_REAL_RATE_MISREPRESENTATION).
3. Odrzucenie wyliczenia pochodnego bez jednoznacznego przypisania obu źródeł (UNCITED_NUMERIC_CLAIM).
4. Odrzucenie wyliczenia pochodnego o błędnej wartości matematycznej (UNAPPROVED_NUMERIC_CLAIM).
5. Akceptację prawidłowo udokumentowanego wyliczenia gdy okresy są porównywalne i aktualne.
6. Akceptację prawidłowo udokumentowanego wyliczenia w ujęciu historycznym/poglądowym dla archiwalnego CPI.
7. Pełny przebieg E2E: GPT-mock -> walidator -> SQLite v2 -> HTML -> Flask bez płatnych API.
"""

from datetime import datetime, timezone
import json
import uuid
import pytest

from app import server, set_db, set_storage_v2
from modules.connectors.base import MacroObservation, RawEvidence
from modules.evaluator import EconomyEvaluator
from modules.pipeline_v2 import MacroPipelineV2
from modules.storage_v2 import SQLiteV2Storage


def _make_run_0ae790030b39_obs_and_citations():
    """Generuje dokładne obserwacje z bieżącego przebiegu RUN_0ae790030b39."""
    verified_obs = [
        {
            "observation_id": "OBS_API_785c81f9dae9",
            "indicator_code": "PL_CPI_YOY",
            "name_pl": "Inflacja CPI r/r",
            "country_code": "PL",
            "value_decimal": "2.3",
            "unit_code": "PCT",
            "period_start": "2025-12-01",
            "period_end": "2025-12-31",
            "source_id": "SRC_GUS_DBW",
            "source_url": "https://api-dbw.stat.gov.pl/api/variable/variable-data-section?id-zmienna=305&id-przekroj=736&id-rok=2025&id-okres=258",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_2c6c55673cc6",
            "indicator_code": "PL_FX_EUR_PLN",
            "name_pl": "Kurs EUR/PLN (NBP)",
            "country_code": "PL",
            "value_decimal": "4.3916",
            "unit_code": "EUR_PLN",
            "period_start": "2026-11-05",
            "period_end": "2026-11-05",
            "source_id": "SRC_NBP",
            "source_url": "https://api.nbp.pl/api/exchangerates/rates/A/EUR/?format=json",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_99127673934a",
            "indicator_code": "PL_FX_USD_PLN",
            "name_pl": "Kurs USD/PLN (NBP)",
            "country_code": "PL",
            "value_decimal": "3.9101",
            "unit_code": "USD_PLN",
            "period_start": "2026-11-05",
            "period_end": "2026-11-05",
            "source_id": "SRC_NBP",
            "source_url": "https://api.nbp.pl/api/exchangerates/rates/A/USD/?format=json",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_03490a76bb44",
            "indicator_code": "PL_GDP_QOQ",
            "name_pl": "Wzrost PKB k/k",
            "country_code": "PL",
            "value_decimal": "1.1",
            "unit_code": "PCT",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "source_id": "SRC_EUROSTAT",
            "source_url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp?format=JSON&lang=en&na_item=B1GQ&s_adj=SCA&unit=CLV_PCH_PRE&geo=PL",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_3f720fb10bad",
            "indicator_code": "PL_GDP_VOLUME",
            "name_pl": "Wolumen PKB",
            "country_code": "PL",
            "value_decimal": "154972.9",
            "unit_code": "MEUR",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "source_id": "SRC_EUROSTAT",
            "source_url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp?format=JSON&lang=en&na_item=B1GQ&s_adj=SCA&unit=CLV10_MEUR&geo=PL",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_593955b627bd",
            "indicator_code": "PL_GDP_YOY",
            "name_pl": "Wzrost PKB r/r",
            "country_code": "PL",
            "value_decimal": "4.0",
            "unit_code": "PCT",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "source_id": "SRC_EUROSTAT",
            "source_url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp?format=JSON&lang=en&na_item=B1GQ&s_adj=SCA&unit=CLV_PCH_SM&geo=PL",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_e9e90b9c53da",
            "indicator_code": "PL_HICP_YOY",
            "name_pl": "Zharmonizowana inflacja HICP r/r",
            "country_code": "PL",
            "value_decimal": "4.0",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "source_id": "SRC_EUROSTAT",
            "source_url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/teicp000?format=JSON&lang=en&geo=PL",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_006680039dec",
            "indicator_code": "PL_NBP_REFERENCE_RATE",
            "name_pl": "Stopa referencyjna NBP (oficjalna)",
            "country_code": "PL",
            "value_decimal": "3.75",
            "unit_code": "PCT",
            "period_start": "2026-03-05",
            "period_end": "2026-03-05",
            "source_id": "SRC_NBP",
            "source_url": "https://static.nbp.pl/dane/stopy/stopy_procentowe.xml",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_ac9fad3ea0c5",
            "indicator_code": "PL_UNEMPLOYMENT_LFS_RATE",
            "name_pl": "Stopa bezrobocia BAEL/LFS",
            "country_code": "PL",
            "value_decimal": "3.4",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "source_id": "SRC_EUROSTAT",
            "source_url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m?format=JSON&lang=en&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT&geo=PL",
            "status": "VERIFIED",
        },
        {
            "observation_id": "OBS_API_020a2510b94a",
            "indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE",
            "name_pl": "Stopa bezrobocia rejestrowanego",
            "country_code": "PL",
            "value_decimal": "5.7",
            "unit_code": "PCT",
            "period_start": "2025-01-01",
            "period_end": "2025-12-31",
            "source_id": "SRC_GUS_BDL",
            "source_url": "https://bdl.stat.gov.pl/api/v1/data/by-variable/60270?unit-level=0&format=json",
            "status": "VERIFIED",
        },
    ]

    # Budowa rejestru cytowań z zachowaniem porządku alfabetycznego (PL_CPI_YOY -> [1], PL_NBP_REFERENCE_RATE -> [8])
    citations = []
    for idx, o in enumerate(sorted(verified_obs, key=lambda x: x["indicator_code"]), start=1):
        inst = "NBP" if "NBP" in o["source_id"] else ("Eurostat" if "EUROSTAT" in o["source_id"] else "GUS")
        citations.append({
            "idx": idx,
            "institution": inst,
            "indicator_code": o["indicator_code"],
            "indicator_name": o["name_pl"],
            "period": f"{o['period_start']} – {o['period_end']}",
            "url": o["source_url"],
            "is_official": True,
            "value_decimal": o["value_decimal"],
        })

    return verified_obs, citations


def test_run_0ae790030b39_archival_cpi_exact_sentence_rejected():
    """Weryfikuje odtworzony przebieg RUN_0ae790030b39:
    Zdanie prezentujące różnicę stopy NBP (2026-03-05) i archiwalnej CPI (2025-12-31, opóźnienie ~309 dni)
    jako 'obecną stopę referencyjną ... dającą realną stopę referencyjną na poziomie +1.45 p.p.'
    musi zostać bezwzględnie odrzucone przez walidator.
    """
    evaluator = EconomyEvaluator()
    verified_obs, citations = _make_run_0ae790030b39_obs_and_citations()

    # Dokładne twierdzenia claims
    claims = [
        {
            "indicator_code": "PL_CPI_YOY",
            "observation_id": "OBS_API_785c81f9dae9",
            "value_decimal": "2.3",
            "unit_code": "PCT",
            "period_start": "2025-12-01",
            "period_end": "2025-12-31",
            "citation_idx": 1,
        },
        {
            "indicator_code": "PL_NBP_REFERENCE_RATE",
            "observation_id": "OBS_API_006680039dec",
            "value_decimal": "3.75",
            "unit_code": "PCT",
            "period_start": "2026-03-05",
            "period_end": "2026-03-05",
            "citation_idx": 8,
        },
    ]

    # Dokładny tekst ze zgłoszenia RUN_0ae790030b39
    candidate = {
        "claims": claims,
        "sections": {
            "1": "Inflacja CPI wynosi 2.3% [1].",
            "2": "Ryzyka gospodarcze.",
            "3": "- **Kredyty i Raty:** Obecna stopa referencyjna NBP wynosi 3.75% [8], co w połączeniu z inflacją CPI na poziomie 2.3% [1] daje realną stopę referencyjną na poziomie +1.45 p.p. To może oznaczać stabilne koszty kredytów.\n- **Ceny i Zakupy:** Ceny stabilne.\n- **Praca i Zarobki:** Rynek stabilny.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }

    parsed = evaluator._parse_candidate_payload(
        candidate=candidate,
        citations=citations,
        verified_obs=verified_obs,
        require_json=True,
    )

    with pytest.raises(ValueError) as excinfo:
        evaluator._validate_structured_report(
            structured_data=parsed,
            citations=citations,
            verified_obs=verified_obs,
            report_date="05.11.2026",
            run_id="RUN_0ae790030b39",
        )

    # Walidator jednoznacznie odrzuca nieuprawnioną prezentację archiwalnej CPI jako bieżącej realnej stopy
    err_str = str(excinfo.value)
    assert "Nie wolno prezentować różnicy stopy NBP i archiwalnej inflacji CPI jako bieżącej realnej stopy procentowej" in err_str


def test_derived_calculation_unreferenced_rejected():
    """Weryfikuje, że liczba odpowiadająca wyliczeniu (+1.45 p.p.) bez podania OBU przypisów [8] i [1]
    jest odrzucana jako UNCITED_NUMERIC_CLAIM.
    """
    evaluator = EconomyEvaluator()
    verified_obs, citations = _make_run_0ae790030b39_obs_and_citations()

    claims = [
        {
            "indicator_code": "PL_CPI_YOY",
            "observation_id": "OBS_API_785c81f9dae9",
            "value_decimal": "2.3",
            "unit_code": "PCT",
            "period_start": "2025-12-01",
            "period_end": "2025-12-31",
            "citation_idx": 1,
        },
        {
            "indicator_code": "PL_NBP_REFERENCE_RATE",
            "observation_id": "OBS_API_006680039dec",
            "value_decimal": "3.75",
            "unit_code": "PCT",
            "period_start": "2026-03-05",
            "period_end": "2026-03-05",
            "citation_idx": 8,
        },
    ]

    # Brak przypisu do CPI [1] w zdaniu z wyliczeniem
    candidate = {
        "claims": claims,
        "sections": {
            "1": "Inflacja CPI wynosi 2.3% [1].",
            "2": "Ryzyka gospodarcze.",
            "3": "- **Kredyty i Raty:** Stopa referencyjna wynosi 3.75% [8], co daje realną stopę referencyjną na poziomie +1.45 p.p.\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }

    parsed = evaluator._parse_candidate_payload(
        candidate=candidate,
        citations=citations,
        verified_obs=verified_obs,
        require_json=True,
    )

    with pytest.raises(ValueError) as excinfo:
        evaluator._validate_structured_report(
            structured_data=parsed,
            citations=citations,
            verified_obs=verified_obs,
            report_date="05.11.2026",
            run_id="RUN_TEST",
        )

    err_str = str(excinfo.value)
    assert "bez jednoznacznego przypisania obu źródeł" in err_str or "[1]" in err_str


def test_derived_calculation_wrong_math_rejected():
    """Weryfikuje, że podanie zmyślonej/błędnej wartości wyliczenia (np. +2.50 p.p. zamiast +1.45 p.p.)
    jest bezwzględnie blokowane.
    """
    evaluator = EconomyEvaluator()
    verified_obs, citations = _make_run_0ae790030b39_obs_and_citations()

    claims = [
        {
            "indicator_code": "PL_CPI_YOY",
            "observation_id": "OBS_API_785c81f9dae9",
            "value_decimal": "2.3",
            "unit_code": "PCT",
            "period_start": "2025-12-01",
            "period_end": "2025-12-31",
            "citation_idx": 1,
        },
        {
            "indicator_code": "PL_NBP_REFERENCE_RATE",
            "observation_id": "OBS_API_006680039dec",
            "value_decimal": "3.75",
            "unit_code": "PCT",
            "period_start": "2026-03-05",
            "period_end": "2026-03-05",
            "citation_idx": 8,
        },
    ]

    # Zmyślone wyliczenie: +2.50 p.p. [8][1]
    candidate = {
        "claims": claims,
        "sections": {
            "1": "Inflacja CPI wynosi 2.3% [1].",
            "2": "Ryzyka gospodarcze.",
            "3": "- **Kredyty i Raty:** Stopa referencyjna wynosi 3.75% [8], inflacja CPI to 2.3% [1], co daje realną stopę +2.50 p.p. [8][1]\n- **Ceny i Zakupy:** Ceny.\n- **Praca i Zarobki:** Praca.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }

    parsed = evaluator._parse_candidate_payload(
        candidate=candidate,
        citations=citations,
        verified_obs=verified_obs,
        require_json=True,
    )

    with pytest.raises(ValueError) as excinfo:
        evaluator._validate_structured_report(
            structured_data=parsed,
            citations=citations,
            verified_obs=verified_obs,
            report_date="05.11.2026",
            run_id="RUN_TEST",
        )

    err_str = str(excinfo.value)
    assert "+2.50" in err_str or "2.50" in err_str or "nie posiada zatwierdzonego twierdzenia" in err_str


def test_derived_calculation_comparable_periods_passes():
    """Weryfikuje, że gdy okresy CPI i NBP są świeże i porównywalne (np. stopa z 2026-09-05, CPI z 2026-09),
    prezentacja wyliczenia realnej stopy z oboma przypisami przechodzi walidację sukcesem.
    """
    evaluator = EconomyEvaluator()
    verified_obs, _ = _make_run_0ae790030b39_obs_and_citations()

    # Podmiana okresów na porównywalne i bieżące
    for o in verified_obs:
        if o["indicator_code"] == "PL_CPI_YOY":
            o["period_start"] = "2026-09-01"
            o["period_end"] = "2026-09-30"
        if o["indicator_code"] == "PL_NBP_REFERENCE_RATE":
            o["period_start"] = "2026-09-05"
            o["period_end"] = "2026-09-05"

    citations = []
    for idx, o in enumerate(sorted(verified_obs, key=lambda x: x["indicator_code"]), start=1):
        inst = "NBP" if "NBP" in o["source_id"] else ("Eurostat" if "EUROSTAT" in o["source_id"] else "GUS")
        citations.append({
            "idx": idx,
            "institution": inst,
            "indicator_code": o["indicator_code"],
            "indicator_name": o["name_pl"],
            "period": f"{o['period_start']} – {o['period_end']}",
            "url": o["source_url"],
            "is_official": True,
            "value_decimal": o["value_decimal"],
        })

    claims = [
        {
            "indicator_code": "PL_CPI_YOY",
            "observation_id": "OBS_API_785c81f9dae9",
            "value_decimal": "2.3",
            "unit_code": "PCT",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "citation_idx": 1,
        },
        {
            "indicator_code": "PL_NBP_REFERENCE_RATE",
            "observation_id": "OBS_API_006680039dec",
            "value_decimal": "3.75",
            "unit_code": "PCT",
            "period_start": "2026-09-05",
            "period_end": "2026-09-05",
            "citation_idx": 8,
        },
    ]

    candidate = {
        "claims": claims,
        "sections": {
            "1": "Inflacja CPI wynosi 2.3% [1].",
            "2": "Ryzyka gospodarcze.",
            "3": "- **Kredyty i Raty:** Stopa referencyjna NBP wynosi 3.75% [8], co w połączeniu z inflacją CPI na poziomie 2.3% [1] daje realną stopę referencyjną na poziomie +1.45 p.p.\n- **Ceny i Zakupy:** Ceny stabilne.\n- **Praca i Zarobki:** Stabilny rynek pracy.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }

    parsed = evaluator._parse_candidate_payload(
        candidate=candidate,
        citations=citations,
        verified_obs=verified_obs,
        require_json=True,
    )

    evaluator._validate_structured_report(
        structured_data=parsed,
        citations=citations,
        verified_obs=verified_obs,
        report_date="05.10.2026",
        run_id="RUN_COMPARABLE_PASS",
    )


def test_derived_calculation_archival_cpi_properly_qualified_passes():
    """Weryfikuje, że w przypadku archiwalnego CPI z grudnia 2025 r.,
    przedstawienie obliczenia jako historycznego/poglądowego z wyraźnym podaniem okresu
    oraz przypisami [8] i [1] jest akceptowane przez walidator.
    """
    evaluator = EconomyEvaluator()
    verified_obs, citations = _make_run_0ae790030b39_obs_and_citations()

    claims = [
        {
            "indicator_code": "PL_CPI_YOY",
            "observation_id": "OBS_API_785c81f9dae9",
            "value_decimal": "2.3",
            "unit_code": "PCT",
            "period_start": "2025-12-01",
            "period_end": "2025-12-31",
            "citation_idx": 1,
        },
        {
            "indicator_code": "PL_NBP_REFERENCE_RATE",
            "observation_id": "OBS_API_006680039dec",
            "value_decimal": "3.75",
            "unit_code": "PCT",
            "period_start": "2026-03-05",
            "period_end": "2026-03-05",
            "citation_idx": 8,
        },
    ]

    candidate = {
        "claims": claims,
        "sections": {
            "1": "Inflacja CPI wynosi 2.3% [1].",
            "2": "Ryzyka gospodarcze.",
            "3": "- **Kredyty i Raty:** Stopa referencyjna NBP wynosi 3.75% [8]. W ujęciu poglądowym dla inflacji CPI z grudnia 2025 roku (2.3% [1]) historyczna realna stopa referencyjna wynosiła +1.45 p.p.\n- **Ceny i Zakupy:** Ceny stabilne.\n- **Praca i Zarobki:** Stabilny rynek.",
            "4": "Przedsiębiorcy.",
            "5": "Podsumowanie.",
        }
    }

    parsed = evaluator._parse_candidate_payload(
        candidate=candidate,
        citations=citations,
        verified_obs=verified_obs,
        require_json=True,
    )

    evaluator._validate_structured_report(
        structured_data=parsed,
        citations=citations,
        verified_obs=verified_obs,
        report_date="05.11.2026",
        run_id="RUN_HISTORICAL_QUALIFIED_PASS",
    )


def test_full_e2e_real_rate_pipeline_mock_sqlite_flask(tmp_path, monkeypatch):
    """Pełny test E2E na izolowanej bazie SQLite bez zewnętrznych płatnych API:
    Ingestion -> Storage v2 -> GPT-mock -> Evaluator / Walidator -> Zapis Raportu -> Generowanie HTML -> Flask Endpoint.
    """
    db_path = str(tmp_path / "economy_agent_v2_test.db")
    storage = SQLiteV2Storage(db_path=db_path)
    evaluator = EconomyEvaluator()

    verified_obs, citations = _make_run_0ae790030b39_obs_and_citations()

    # Zapis surowych dowodów i obserwacji w odizolowanej bazie testowej
    evis = []
    observations = []
    for o in verified_obs:
        evi = RawEvidence(
            evidence_id=f"EVI_{o['indicator_code']}",
            source_id=o["source_id"],
            source_url=o["source_url"],
            document_type="API_RESPONSE",
            content_hash=f"hash_{o['indicator_code']}",
            payload_text=f"Official data {o['indicator_code']} = {o['value_decimal']}",
            status_code=200,
            retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        obs = MacroObservation(
            observation_id=o["observation_id"],
            indicator_code=o["indicator_code"],
            country_code=o["country_code"],
            period_start=o["period_start"],
            period_end=o["period_end"],
            frequency="MONTHLY",
            value_decimal=o["value_decimal"],
            unit_code=o["unit_code"],
            revision_type="FINAL",
            status="VERIFIED",
            evidence_id=evi.evidence_id,
        )
        evis.append(evi)
        observations.append(obs)

    # Przygotowanie poprawnej syntezy GPT z prawidłowo udokumentowaną historyczną realną stopą
    claims_payload = [
        {
            "indicator_code": o["indicator_code"],
            "observation_id": o["observation_id"],
            "value_decimal": o["value_decimal"],
            "unit_code": o["unit_code"],
            "period_start": o["period_start"],
            "period_end": o["period_end"],
            "citation_idx": [c["idx"] for c in citations if c["indicator_code"] == o["indicator_code"]][0],
        }
        for o in verified_obs
    ]

    gpt_response_json = json.dumps({
        "claims": claims_payload,
        "sections": {
            "1": "Inflacja CPI wynosi 2.3% [1], Zharmonizowany HICP 4.0% [7], a PKB r/r 4.0% [6].",
            "2": "Ryzyka gospodarcze i perspektywy wzrostu PKB k/k 1.1% [4], wolumen 154972.9 mln EUR [5].",
            "3": "- **Kredyty i Raty:** Stopa referencyjna NBP wynosi 3.75% [8]. W ujęciu poglądowym dla inflacji CPI z grudnia 2025 roku (2.3% [1]) historyczna realna stopa referencyjna wynosiła +1.45 p.p.\n- **Ceny i Zakupy:** Kurs EUR/PLN wynosi 4.3916 [2], USD/PLN 3.9101 [3].\n- **Praca i Zarobki:** Stopa bezrobocia BAEL/LFS wynosi 3.4% [9], a rejestrowanego 5.7% [10].",
            "4": "Sytuacja przedsiębiorstw w obliczu stóp procentowych.",
            "5": "Podsumowanie wskaźników makroekonomicznych.",
        }
    })

    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: gpt_response_json)

    # Inicjalizacja potoku pipeline v2
    pipeline = MacroPipelineV2(
        db=storage,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=tmp_path / "logs",
    )
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda rid: (evis, observations, [], []))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, rid: [])

    out_html_path = tmp_path / "real_rate_report.html"
    result = pipeline.run(country="Polska", output_html_path=str(out_html_path))

    # Weryfikacja wyniku potoku
    assert result.success is True
    assert result.status in ("COMPLETED", "PARTIAL", "SUCCESS")
    assert result.report_id is not None

    # Weryfikacja bazy danych SQLite
    report_row = storage.get_latest_report("PL")
    assert report_row is not None
    assert report_row["report_id"] == result.report_id
    assert report_row["publication_status"] == "PUBLISHED"
    assert "+1.45 p.p." in report_row["report_markdown"]
    assert "3.75%" in report_row["report_markdown"]
    assert "2.3%" in report_row["report_markdown"]

    # Weryfikacja pliku HTML
    assert out_html_path.exists()
    html_text = out_html_path.read_text(encoding="utf-8")
    assert "+1.45 p.p." in html_text
    assert "3.75%" in html_text
    assert "2.3%" in html_text
    assert "3.4%" in html_text

    # Weryfikacja serwowania przez Flask
    original_storage = getattr(server, "_storage_v2", None)
    original_db = getattr(server, "_db", None)
    monkeypatch.setattr("app.get_last_run_path", lambda: tmp_path / "empty_last_run.json")
    try:
        set_storage_v2(storage)
        set_db(None)
        client = server.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        rendered = resp.get_data(as_text=True)
        assert "+1.45 p.p." in rendered
        assert "3.75%" in rendered
        assert "2.3%" in rendered
    finally:
        set_storage_v2(original_storage)
        set_db(original_db)
