"""Local, secret-safe diagnostic files for pipeline executions."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable, Mapping, Optional

import config


DEFAULT_LOG_DIR = Path("instance") / "logs"
EXPECTED_REPORT_INDICATORS = (
    "PL_CPI_YOY",
    "PL_HICP_YOY",
    "PL_UNEMPLOYMENT_REGISTERED_RATE",
    "PL_UNEMPLOYMENT_LFS_RATE",
    "PL_GDP_QOQ",
    "PL_GDP_YOY",
    "PL_POLICY_RATE_REF",
    "PL_FX_EUR_PLN",
    "PL_FX_USD_PLN",
)

INDICATOR_ALIASES: dict[str, tuple[str, ...]] = {
    "PL_CPI_YOY": ("PL_CPI_YOY",),
    "PL_HICP_YOY": ("PL_HICP_YOY", "EU_HICP_YOY"),
    "PL_UNEMPLOYMENT_REGISTERED_RATE": ("PL_UNEMPLOYMENT_REGISTERED_RATE",),
    "PL_UNEMPLOYMENT_LFS_RATE": (
        "PL_UNEMPLOYMENT_LFS_RATE",
        "PL_UNEMPLOYMENT_HARMONIZED_RATE",
        "EU_UNEMPLOYMENT_RATE",
    ),
    "PL_GDP_QOQ": ("PL_GDP_QOQ", "EU_GDP_QOQ"),
    "PL_GDP_YOY": ("PL_GDP_YOY", "EU_GDP_YOY"),
    "PL_POLICY_RATE_REF": ("PL_POLICY_RATE_REF", "PL_NBP_REFERENCE_RATE"),
    "PL_FX_EUR_PLN": ("PL_FX_EUR_PLN",),
    "PL_FX_USD_PLN": ("PL_FX_USD_PLN",),
}

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\btvly-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)
_NAMED_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:authorization|api[_-]?key|access[_-]?token|token|secret|password)"
    r"\s*[:=]\s*)(?:bearer\s+)?(?:['\"])?[^\s,;}'\"]+"
)
_SENSITIVE_CONTENT_PATTERN = re.compile(
    r"(?i)\b(?:full[_ -]?prompt|prompt|gpt[_ -]?response|model[_ -]?response|completion)"
    r"\s*[:=].*$"
)


def _configured_secrets() -> list[str]:
    values = [
        getattr(config, "OPENAI_API_KEY", None),
        getattr(config, "TAVILY_API_KEY", None),
    ]
    return [str(value) for value in values if value]


def redact_secrets(value: Any, extra_secrets: Iterable[str] = ()) -> str:
    """Return a compact message with credentials and model content removed."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    for secret in [*_configured_secrets(), *[str(item) for item in extra_secrets if item]]:
        text = text.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = _NAMED_SECRET_PATTERN.sub(r"\1[REDACTED]", text)
    text = _SENSITIVE_CONTENT_PATTERN.sub("[REDACTED MODEL CONTENT]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500] + ("..." if len(text) > 500 else "")


def safe_error_message(error: BaseException) -> str:
    """Describe an exception without persisting credentials or full model content."""
    return f"{type(error).__name__}: {redact_secrets(error)}"


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


class _RedactingFormatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


class PipelineDiagnostics:
    """Write rotating event logs, atomic run summary, and structural step trace."""

    def __init__(self, log_dir: os.PathLike[str] | str = DEFAULT_LOG_DIR):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "agent.log"
        self.summary_path = self.log_dir / "last_run.json"
        self.steps_path = self.log_dir / "steps.jsonl"
        logger_name = f"polish_economy_agent.pipeline.{self.log_path.resolve()}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if not self.logger.handlers:
            handler = RotatingFileHandler(
                self.log_path,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(_RedactingFormatter(
                "%(asctime)sZ %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            ))
            self.logger.addHandler(handler)

    def event(self, level: int, message: str, *, run_id: str) -> None:
        self.logger.log(level, "run_id=%s %s", run_id, redact_secrets(message))

    def write_summary(self, summary: Mapping[str, Any]) -> None:
        payload = _sanitize_json(dict(summary))
        payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        temporary_path = self.summary_path.with_suffix(".json.tmp")
        with temporary_path.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_path, self.summary_path)

    def record_step(
        self,
        *,
        run_id: str,
        function: str,
        stage: str,
        duration_ms: float = 0.0,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a structured START, END, or ERROR step trace entry to steps.jsonl."""
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "function": function,
            "funkcja": function,
            "stage": stage,
            "step": stage,
            "etap": stage,
            "duration_ms": round(float(duration_ms), 2) if duration_ms is not None else 0.0,
            "input_summary": redact_secrets(input_summary) if input_summary is not None else None,
            "output_summary": redact_secrets(output_summary) if output_summary is not None else None,
            "error_code": str(error_code) if error_code is not None else None,
            "kod_bledu": str(error_code) if error_code is not None else None,
            "error_message": redact_secrets(error_message) if error_message is not None else None,
            "przyczyna": redact_secrets(error_message) if error_message is not None else None,
        }
        with open(self.steps_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    @contextmanager
    def track_step(
        self,
        *,
        run_id: str,
        function: str,
        input_summary: Optional[str] = None,
    ):
        """Context manager measuring execution duration and emitting START/END/ERROR records."""
        t0 = time.perf_counter()
        self.record_step(
            run_id=run_id,
            function=function,
            stage="START",
            duration_ms=0.0,
            input_summary=input_summary,
        )
        ctx: dict[str, Any] = {"output_summary": None}
        try:
            yield ctx
            duration_ms = (time.perf_counter() - t0) * 1000.0
            self.record_step(
                run_id=run_id,
                function=function,
                stage="END",
                duration_ms=duration_ms,
                input_summary=input_summary,
                output_summary=ctx.get("output_summary"),
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            self.record_step(
                run_id=run_id,
                function=function,
                stage="ERROR",
                duration_ms=duration_ms,
                input_summary=input_summary,
                output_summary=ctx.get("output_summary"),
                error_code=type(exc).__name__,
                error_message=safe_error_message(exc),
            )
            raise


def missing_report_indicators(verified_observations: Iterable[Mapping[str, Any]]) -> list[str]:
    present = {
        str(item.get("indicator_code"))
        for item in verified_observations
        if item.get("indicator_code")
    }
    missing = []
    for canonical_code in EXPECTED_REPORT_INDICATORS:
        aliases = INDICATOR_ALIASES.get(canonical_code, (canonical_code,))
        if not any(alias in present for alias in aliases):
            missing.append(canonical_code)
    return missing


def base_run_summary(*, run_id: str, offline_mode: bool) -> dict[str, Any]:
    return {
        "timestamp_utc": None,
        "run_id": run_id,
        "pipeline_status": "STARTED",
        "offline_mode": offline_mode,
        "model": getattr(config, "DEFAULT_OPENAI_MODEL", None),
        "gpt_attempted": False,
        "generation_mode": "OFFLINE_DEMO" if offline_mode else None,
        "fallback_reason": None,
        "tavily_status": "NOT_RUN",
        "tavily_results_count": 0,
        "verified_indicators_count": 0,
        "missing_indicators": list(EXPECTED_REPORT_INDICATORS),
        "report_id": None,
    }
