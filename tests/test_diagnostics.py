import json

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
