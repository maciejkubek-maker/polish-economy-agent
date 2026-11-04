import json
import pytest

import config
from modules.connectors.base import MacroObservation, RawEvidence
from modules.diagnostics import missing_report_indicators
from modules.evaluator import EconomyEvaluator
from modules.pipeline_v2 import MacroPipelineV2
from modules.storage_v2 import SQLiteV2Storage


SOURCE_URL = "https://api-dbw.stat.gov.pl/api/1.1.0/data/cpi"


def _valid_gpt_report() -> str:
    return f"""# RAPORT KONDYCJI GOSPODARCZEJ: Polska

## 1. Analiza Trendów w Dostępnym Okresie
Inflacja CPI wyniosła 3.1% [1].

## 2. Zagrożenia i Ryzyka Makroekonomiczne
Zakres danych ogranicza siłę wniosków.

## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Odczyt opisuje zmiany cen.

## 4. Co to oznacza dla Przedsiębiorców?
Odczyt nie jest prognozą.

## 5. Podsumowanie i Realistyczny Werdykt
Wnioski pozostają warunkowe.

## 6. Źródła danych i Metodologia
[1] GUS, CPI, {SOURCE_URL}
"""


def _official_data(indicator_code: str = "PL_CPI_YOY"):
    evidence = RawEvidence(
        evidence_id=f"EVI_{indicator_code}",
        source_id="SRC_GUS_DBW" if indicator_code == "PL_CPI_YOY" else "SRC_NBP",
        source_url=SOURCE_URL,
        document_type="API_RESPONSE",
        content_hash=f"hash-{indicator_code}",
        payload_text="official fixture",
        status_code=200,
        retrieved_at_utc="2026-11-04T10:00:00Z",
    )
    observation = MacroObservation(
        indicator_code=indicator_code,
        country_code="PL",
        period_start="2026-09-01" if indicator_code == "PL_CPI_YOY" else "2026-10-30",
        period_end="2026-09-30" if indicator_code == "PL_CPI_YOY" else "2026-10-30",
        frequency="MONTHLY" if indicator_code == "PL_CPI_YOY" else "DAILY",
        value_decimal="3.1" if indicator_code == "PL_CPI_YOY" else "4.3955",
        unit_code="PCT" if indicator_code == "PL_CPI_YOY" else "EUR_PLN",
        revision_type="FINAL",
        status="VERIFIED",
        evidence_id=evidence.evidence_id,
    )
    return [evidence], [observation], [], []


def _make_pipeline(tmp_path, monkeypatch, evaluator, *, offline=False, indicator="PL_CPI_YOY"):
    monkeypatch.setattr(config, "OFFLINE_MODE", offline)
    storage = SQLiteV2Storage(db_path=str(tmp_path / "diagnostics_v2.db"))
    pipeline = MacroPipelineV2(
        db=storage,
        offline_mode=offline,
        evaluator=evaluator,
        diagnostics_dir=tmp_path / "logs",
    )
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda run_id: _official_data(indicator))
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, run_id: [])
    return pipeline


def _read_summary(tmp_path):
    return json.loads((tmp_path / "logs" / "last_run.json").read_text(encoding="utf-8"))


def test_diagnostics_record_validated_gpt_success(tmp_path, monkeypatch):
    evaluator = EconomyEvaluator()
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: _valid_gpt_report())
    result = _make_pipeline(tmp_path, monkeypatch, evaluator).run()

    summary = _read_summary(tmp_path)
    assert result.success is True
    assert summary["generation_mode"] == "LIVE_AI_VALIDATED"
    assert summary["gpt_attempted"] is True
    assert summary["fallback_reason"] is None
    assert summary["report_id"] == result.report_id
    assert (tmp_path / "logs" / "agent.log").exists()


def test_diagnostics_distinguish_gpt_api_error(tmp_path, monkeypatch):
    evaluator = EconomyEvaluator()
    monkeypatch.setattr(
        evaluator,
        "_run_llm_synthesis",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("quota exceeded")),
    )
    result = _make_pipeline(tmp_path, monkeypatch, evaluator).run()

    summary = _read_summary(tmp_path)
    assert result.success is False
    assert result.status == "FAILED"
    assert result.report_id is None
    assert summary["pipeline_status"] == "FAILED"
    assert summary["report_id"] is None
    assert summary["gpt_attempted"] is True
    assert summary["generation_mode"] == "GPT_API_ERROR"
    assert summary["fallback_reason"] == "Błąd API GPT: RuntimeError: quota exceeded"


def test_diagnostics_distinguish_gpt_validation_rejection(tmp_path, monkeypatch):
    evaluator = EconomyEvaluator()
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: "invalid report")
    result = _make_pipeline(tmp_path, monkeypatch, evaluator).run()

    summary = _read_summary(tmp_path)
    assert result.success is False
    assert result.status == "FAILED"
    assert result.report_id is None
    assert summary["pipeline_status"] == "FAILED"
    assert summary["report_id"] is None
    assert summary["gpt_attempted"] is True
    assert summary["generation_mode"] == "GPT_VALIDATION_REJECTED"
    assert "wymaganej struktury" in summary["fallback_reason"]
    assert "Błąd API GPT" not in summary["fallback_reason"]


def test_diagnostics_failure_before_gpt_is_not_gpt_api_error(tmp_path, monkeypatch):
    evaluator = EconomyEvaluator()
    pipeline = _make_pipeline(tmp_path, monkeypatch, evaluator, offline=False)
    monkeypatch.setattr(
        pipeline,
        "store_official_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("db disk write failure")),
    )
    result = pipeline.run()

    summary = _read_summary(tmp_path)
    assert result.success is False
    assert result.status == "FAILED"
    assert summary["pipeline_status"] == "FAILED"
    assert summary["report_id"] is None
    assert summary["gpt_attempted"] is False
    assert summary["generation_mode"] is None
    assert "db disk write failure" in summary["fallback_reason"]


def test_diagnostics_list_missing_cpi(tmp_path, monkeypatch):
    pipeline = _make_pipeline(
        tmp_path,
        monkeypatch,
        EconomyEvaluator(),
        offline=True,
        indicator="PL_FX_EUR_PLN",
    )
    result = pipeline.run()

    summary = _read_summary(tmp_path)
    assert result.success is True
    assert summary["generation_mode"] == "OFFLINE_DEMO"
    assert summary["gpt_attempted"] is False
    assert "PL_CPI_YOY" in summary["missing_indicators"]


def test_missing_report_indicators_accounts_for_connector_aliases():
    # Rzeczywiste kody zwracane przez konektory Eurostat i NBP:
    # Eurostat zwraca EU_HICP_YOY zamiast PL_HICP_YOY
    # NBP zwraca PL_NBP_REFERENCE_RATE zamiast PL_POLICY_RATE_REF
    observations = [
        {"indicator_code": "PL_CPI_YOY"},
        {"indicator_code": "EU_HICP_YOY"},
        {"indicator_code": "PL_UNEMPLOYMENT_REGISTERED_RATE"},
        {"indicator_code": "PL_UNEMPLOYMENT_LFS_RATE"},
        {"indicator_code": "PL_GDP_QOQ"},
        {"indicator_code": "PL_GDP_YOY"},
        {"indicator_code": "PL_NBP_REFERENCE_RATE"},
        {"indicator_code": "PL_FX_EUR_PLN"},
        {"indicator_code": "PL_FX_USD_PLN"},
    ]
    missing = missing_report_indicators(observations)
    assert missing == [], f"Oczekiwano pustej listy braków przy obecności aliasów, otrzymano: {missing}"

    # Gdy brakuje CPI
    missing_without_cpi = missing_report_indicators(observations[1:])
    assert missing_without_cpi == ["PL_CPI_YOY"]


def test_diagnostics_persist_failed_pipeline_as_failed(tmp_path, monkeypatch):
    pipeline = _make_pipeline(tmp_path, monkeypatch, EconomyEvaluator(), offline=True)
    monkeypatch.setattr(
        pipeline,
        "store_official_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    result = pipeline.run()

    summary = _read_summary(tmp_path)
    assert result.success is False
    assert result.status == "FAILED"
    assert summary["pipeline_status"] == "FAILED"
    assert summary["report_id"] is None
    assert summary["fallback_reason"] == "OSError: disk unavailable"


def test_diagnostics_redact_secrets_headers_and_model_content(tmp_path, monkeypatch):
    secret = "unit-test-secret-value-123456789"
    prompt = "full confidential prompt with private instructions"
    monkeypatch.setattr(config, "OPENAI_API_KEY", secret)
    pipeline = _make_pipeline(tmp_path, monkeypatch, EconomyEvaluator(), offline=False)
    monkeypatch.setattr(
        pipeline,
        "store_official_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(f"Authorization: Bearer {secret}; prompt: {prompt}")
        ),
    )
    pipeline.run()

    summary_text = (tmp_path / "logs" / "last_run.json").read_text(encoding="utf-8")
    log_text = (tmp_path / "logs" / "agent.log").read_text(encoding="utf-8")
    combined = summary_text + log_text
    assert secret not in combined
    assert prompt not in combined
    assert "Bearer" not in combined
    assert "[REDACTED]" in combined


def test_validator_rejects_mismatched_footnote_attribution(tmp_path, monkeypatch):
    """Walidator odrzuca raport, gdy model przypisuje liczbę do niewłaściwego źródła."""
    evaluator = EconomyEvaluator()
    storage = SQLiteV2Storage(db_path=str(tmp_path / "mismatch_test.db"))
    pipeline = MacroPipelineV2(
        db=storage,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=tmp_path / "logs",
    )
    # W bazie mamy zweryfikowane CPI (3.1%, [1]) oraz stopę NBP (5.75%, [2])
    def mock_official_two(run_id):
        evi_cpi, obs_cpi, _, _ = _official_data("PL_CPI_YOY")
        evi_nbp = RawEvidence(
            evidence_id="EVI_PL_POLICY_RATE_REF",
            source_id="SRC_NBP",
            source_url="https://api.nbp.pl/stopy",
            document_type="API_RESPONSE",
            content_hash="hash-nbp-ref",
            payload_text="official nbp",
            status_code=200,
            retrieved_at_utc="2026-11-04T10:00:00Z",
        )
        obs_nbp = MacroObservation(
            indicator_code="PL_POLICY_RATE_REF",
            country_code="PL",
            period_start="2026-10-01",
            period_end="2026-10-31",
            frequency="MONTHLY",
            value_decimal="5.75",
            unit_code="PCT",
            revision_type="FINAL",
            status="VERIFIED",
            evidence_id=evi_nbp.evidence_id,
        )
        return evi_cpi + [evi_nbp], obs_cpi + [obs_nbp], [], []

    monkeypatch.setattr(pipeline, "fetch_official_data", mock_official_two)
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, run_id: [])

    # Obie liczby (3.1% oraz 5.75%) są zweryfikowane w bazie.
    # Jednak GPT przypisuje stopę 5.75% do źródła [1] (które jest źródłem CPI o wartości 3.1%)
    mismatched_report = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska

## 1. Analiza Trendów w Dostępnym Okresie
Stopa referencyjna NBP wynosi 5.75% [1], a inflacja CPI wynosi 3.1% [2].

## 2. Zagrożenia i Ryzyka Makroekonomiczne
Ryzyka pozostają istotne.

## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Odczyt nie przesądza kosztu rat.

## 4. Co to oznacza dla Przedsiębiorców?
Brak prognozy.

## 5. Podsumowanie i Realistyczny Werdykt
Wnioski warunkowe.

## 6. Źródła danych i Metodologia
[1] Główny Urząd Statystyczny - https://stat.gov.pl
[2] Narodowy Bank Polski - https://nbp.pl
"""
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: mismatched_report)
    result = pipeline.run()

    summary = _read_summary(tmp_path)
    assert result.success is False
    assert result.status == "FAILED"
    assert summary["generation_mode"] == "GPT_VALIDATION_REJECTED"
    assert "Niepoprawne powiązanie przypisów ze źródłami" in summary["fallback_reason"]
    assert "5.75%" in summary["fallback_reason"]


def test_validator_rejects_unverified_tavily_numbers(tmp_path, monkeypatch):
    """Wartości z Tavily nie mogą być automatycznie traktowane jako oficjalne zweryfikowane obserwacje."""
    evaluator = EconomyEvaluator()
    storage = SQLiteV2Storage(db_path=str(tmp_path / "tavily_test.db"))
    pipeline = MacroPipelineV2(
        db=storage,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=tmp_path / "logs",
    )
    # Brak CPI w oficjalnych danych — oficjalnie mamy tylko kurs walutowy 4.3955
    monkeypatch.setattr(pipeline, "fetch_official_data", lambda run_id: _official_data("PL_FX_EUR_PLN"))

    # Tavily zwraca artykuł prasowy z informacją o inflacji 3.1%
    tavily_news = [{
        "title": "GUS: Wskaźniki cen",
        "url": "https://stat.gov.pl/wiadomosc-cpi.html",
        "content": "Ceny wzrosły o 3.1% r/r",
        "published_date": "2026-10-15",
        "domain": "stat.gov.pl",
        "source_classification": "OFFICIAL_COMMUNIQUE",
        "topic": "INFLATION",
        "query": "inflacja",
    }]
    monkeypatch.setattr(pipeline, "search_enrichment", lambda country, run_id: tavily_news)

    # GPT próbuje zacytować 3.1% jako potwierdzoną liczbę makroekonomiczną
    gpt_claim_tavily = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska

## 1. Analiza Trendów w Dostępnym Okresie
Inflacja CPI wyniosła 3.1% [2].

## 2. Zagrożenia i Ryzyka Makroekonomiczne
Niepewność co do dynamiki cen.

## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Ceny rosną.

## 4. Co to oznacza dla Przedsiębiorców?
Koszty rosną.

## 5. Podsumowanie i Realistyczny Werdykt
Brak oficjalnego potwierdzenia.

## 6. Źródła danych i Metodologia
[1] NBP, kurs EUR/PLN, https://api.nbp.pl
[2] Media, GUS: Wskaźniki cen, https://stat.gov.pl/wiadomosc-cpi.html
"""
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: gpt_claim_tavily)
    result = pipeline.run()

    summary = _read_summary(tmp_path)
    assert result.success is False
    assert result.status == "FAILED"
    assert summary["generation_mode"] == "GPT_VALIDATION_REJECTED"
    # Walidator odrzuca 3.1% jako niezweryfikowaną liczbę, ponieważ Tavily nie tworzy oficjalnych obserwacji
    assert "Niezweryfikowane twierdzenia liczbowe" in summary["fallback_reason"]
    assert "3.1%" in summary["fallback_reason"]


def test_validator_rejects_missing_url_and_logs_exact_url():
    """Walidator bezpośrednio odrzuca raport, gdy w tekście brak wymaganego URL-a i loguje dokładny URL."""
    evaluator = EconomyEvaluator()
    sample_report = """# RAPORT KONDYCJI GOSPODARCZEJ: Polska

## 1. Analiza Trendów w Dostępnym Okresie
Inflacja CPI wyniosła 3.1% [1].

## 2. Zagrożenia i Ryzyka Makroekonomiczne
Ryzyka.

## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Brak.

## 4. Co to oznacza dla Przedsiębiorców?
Brak.

## 5. Podsumowanie i Realistyczny Werdykt
Brak.

## 6. Źródła danych i Metodologia
[1] GUS, brak adresu
"""
    citations = [{
        "idx": 1,
        "institution": "GUS",
        "indicator_name": "CPI",
        "period": "2026-09",
        "url": "https://api-dbw.stat.gov.pl/api/1.1.0/exact-endpoint-test",
        "is_official": True,
        "value_decimal": "3.1",
    }]
    verified_obs = [{
        "indicator_code": "PL_CPI_YOY",
        "value_decimal": "3.1",
    }]

    with pytest.raises(ValueError) as exc_info:
        evaluator._validate_v2_report(sample_report, citations, verified_obs)

    err = str(exc_info.value)
    assert "Raport nie zawiera bezpośrednich URL-i cytowanych źródeł" in err
    assert "https://api-dbw.stat.gov.pl/api/1.1.0/exact-endpoint-test" in err


def test_pipeline_steps_jsonl_records_structured_events(tmp_path, monkeypatch):
    """steps.jsonl zawiera rekordy START i END dla kluczowych etapów potoku z kompletnymi polami."""
    storage = SQLiteV2Storage(db_path=str(tmp_path / "steps_test.db"))
    evaluator = EconomyEvaluator()

    def mock_synth(country, report_date, periods_summary, chronological_context, **kwargs):
        import re
        match = re.search(r"-\s*([^:]+):\s*([0-9.,]+)\s*%\s*[^\[]*\[(\d+)\]", chronological_context)
        if match:
            ind_name, val, fn = match.group(1).strip(), match.group(2).strip(), match.group(3).strip()
            claim = f"{ind_name} wyniosła {val}% [{fn}]."
        else:
            claim = "Wskaźnik wyniósł 4.0% [1]."
        return f"""# RAPORT KONDYCJI GOSPODARCZEJ: Polska

## 1. Analiza Trendów w Dostępnym Okresie
{claim}

## 2. Zagrożenia i Ryzyka Makroekonomiczne
Ryzyka makroekonomiczne.

## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)
Perspektywa obywatela.

## 4. Co to oznacza dla Przedsiębiorców?
Perspektywa przedsiębiorcy.

## 5. Podsumowanie i Realistyczny Werdykt
Podsumowanie analizy.

## 6. Źródła danych i Metodologia
"""

    monkeypatch.setattr(evaluator, "_run_llm_synthesis", mock_synth)
    pipeline = MacroPipelineV2(
        db=storage,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=tmp_path / "logs",
    )
    pipeline._register_offline_fixtures()
    pipeline.nbp.offline_mode = True
    pipeline.eurostat.offline_mode = True
    pipeline.gus.offline_mode = True
    pipeline.search_service.offline_mode = True
    html_out = str(tmp_path / "report.html")
    result = pipeline.run(output_html_path=html_out)

    assert result.success is True
    steps_file = tmp_path / "logs" / "steps.jsonl"
    assert steps_file.exists(), "Plik steps.jsonl musi istnieć"

    lines = [json.loads(line) for line in steps_file.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) >= 8

    required_keys = {
        "timestamp_utc",
        "run_id",
        "function",
        "funkcja",
        "stage",
        "step",
        "etap",
        "duration_ms",
        "input_summary",
        "output_summary",
        "error_code",
        "kod_bledu",
        "error_message",
        "przyczyna",
    }
    for record in lines:
        for k in required_keys:
            assert k in record, f"Brak klucza {k} w rekordzie steps.jsonl: {record}"
        assert record["run_id"] == result.run_id

    functions = {r["function"] for r in lines}
    expected_functions = {
        "fetch_nbp",
        "fetch_eurostat",
        "fetch_gus",
        "search_tavily",
        "gpt_synthesis",
        "validate_report",
        "store_sqlite",
        "write_html",
    }
    for fn in expected_functions:
        assert fn in functions, f"Brak funkcji {fn} w steps.jsonl (zarejestrowano: {functions})"

    # Sprawdzenie etapów START i END dla validate_report i gpt_synthesis
    val_stages = [r["stage"] for r in lines if r["function"] == "validate_report"]
    assert "START" in val_stages
    assert "END" in val_stages

    # duration_ms na END musi być >= 0
    end_records = [r for r in lines if r["stage"] == "END"]
    for r in end_records:
        assert r["duration_ms"] >= 0.0


def test_pipeline_steps_jsonl_records_error_events(tmp_path, monkeypatch):
    """steps.jsonl rejestruje etap ERROR z kodem błędu i przyczyną przy odrzuceniu przez walidator."""
    evaluator = EconomyEvaluator()
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: "niepoprawny raport")
    pipeline = _make_pipeline(tmp_path, monkeypatch, evaluator)
    result = pipeline.run()

    assert result.success is False
    steps_file = tmp_path / "logs" / "steps.jsonl"
    assert steps_file.exists()

    lines = [json.loads(line) for line in steps_file.read_text(encoding="utf-8").strip().splitlines()]
    val_errors = [r for r in lines if r["function"] == "validate_report" and r["stage"] == "ERROR"]
    assert len(val_errors) == 1
    err_rec = val_errors[0]
    assert err_rec["error_code"] == "VALIDATION_FAILED"
    assert "Raport nie zachowuje wymaganej struktury" in err_rec["error_message"]
    assert err_rec["duration_ms"] >= 0.0


def test_validator_diagnostics_logged_to_run_log_file(tmp_path, monkeypatch):
    """Diagnostyka walidatora (ostrzeżenia i sukces) trafia do agent.log z run_id danego przebiegu."""
    evaluator = EconomyEvaluator()
    # 1. Przebieg z błędem walidacji
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: "błędna treść")
    pipeline_fail = _make_pipeline(tmp_path, monkeypatch, evaluator)
    res_fail = pipeline_fail.run()

    log_path = tmp_path / "logs" / "agent.log"
    assert log_path.exists()
    log_content = log_path.read_text(encoding="utf-8")
    assert f"run_id={res_fail.run_id}" in log_content
    assert "Validator rejection: Raport nie zachowuje wymaganej struktury" in log_content

    # 2. Przebieg z sukcesem walidacji (nowa baza na odrębny przebieg)
    storage_ok = SQLiteV2Storage(db_path=str(tmp_path / "ok_test.db"))
    pipeline_ok = MacroPipelineV2(
        db=storage_ok,
        offline_mode=False,
        evaluator=evaluator,
        diagnostics_dir=tmp_path / "logs",
    )
    monkeypatch.setattr(pipeline_ok, "fetch_official_data", lambda run_id: _official_data("PL_CPI_YOY"))
    monkeypatch.setattr(pipeline_ok, "search_enrichment", lambda country, run_id: [])
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: _valid_gpt_report())
    res_ok = pipeline_ok.run()
    log_content_after = log_path.read_text(encoding="utf-8")
    assert f"run_id={res_ok.run_id}" in log_content_after
    assert "Validator passed: structure, footnotes, direct URLs and numbers verified" in log_content_after


def test_last_run_json_updated_at_pipeline_start(tmp_path, monkeypatch):
    """last_run.json jest tworzony/aktualizowany już przy rozpoczęciu przebiegu (status STARTED)."""
    evaluator = EconomyEvaluator()
    monkeypatch.setattr(evaluator, "_run_llm_synthesis", lambda *args, **kwargs: _valid_gpt_report())
    pipeline = _make_pipeline(tmp_path, monkeypatch, evaluator)

    observed_status_at_start = []

    orig_fetch = pipeline.fetch_official_data
    def intercepting_fetch(run_id):
        # Podczas pobierania danych sprawdzamy zawartość last_run.json
        summary = _read_summary(tmp_path)
        observed_status_at_start.append(summary.copy())
        return orig_fetch(run_id)

    monkeypatch.setattr(pipeline, "fetch_official_data", intercepting_fetch)
    result = pipeline.run()

    assert result.success is True
    assert len(observed_status_at_start) == 1
    start_summary = observed_status_at_start[0]
    assert start_summary["pipeline_status"] == "STARTED"
    assert start_summary["run_id"] == result.run_id

    # Po zakończeniu status zmienia się na COMPLETED/PARTIAL
    final_summary = _read_summary(tmp_path)
    assert final_summary["pipeline_status"] in {"COMPLETED", "PARTIAL"}
    assert final_summary["run_id"] == result.run_id


def test_steps_jsonl_redacts_secrets(tmp_path, monkeypatch):
    """steps.jsonl redaguje sekrety z pól input_summary, output_summary i error_message."""
    secret = "sk-test-secret-key-1234567890"
    monkeypatch.setattr(config, "OPENAI_API_KEY", secret)
    evaluator = EconomyEvaluator()
    monkeypatch.setattr(
        evaluator,
        "_run_llm_synthesis",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(f"Unauthorized with {secret}")),
    )
    pipeline = _make_pipeline(tmp_path, monkeypatch, evaluator)
    pipeline.run()

    steps_text = (tmp_path / "logs" / "steps.jsonl").read_text(encoding="utf-8")
    assert secret not in steps_text
    assert "[REDACTED]" in steps_text
