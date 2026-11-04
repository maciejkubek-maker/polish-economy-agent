"""
Aplikacja Polish Economy Agent.
Uruchamia potok danych makroekonomicznych v2 oraz serwuje raport analityczny.
"""

import base64
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re
from typing import Optional
from urllib.parse import urlparse
from flask import Flask, send_file
import config
from modules.database import EconomyDatabase
from modules.evaluator import EconomyEvaluator
from modules.sources import PolishEconomySourceChecker
from modules.storage_v2 import SQLiteV2Storage

server = Flask(__name__)
_db = None
_storage_v2 = None


def get_db() -> EconomyDatabase:
  """Zwraca instancję bazy danych z leniwą inicjalizacją (nie obciąża importu modułu)."""
  global _db
  if _db is None:
    _db = EconomyDatabase()
  return _db


def set_db(database: Optional[EconomyDatabase]):
  """Umożliwia wstrzyknięcie izolowanej instancji bazy danych (np. w testach)."""
  global _db
  _db = database


def get_storage_v2() -> Optional[SQLiteV2Storage]:
  """Zwraca instancję bazy SQLite v2 z leniwą inicjalizacją."""
  global _storage_v2
  if _storage_v2 is None:
    v2_path = getattr(config, "DB_V2_PATH", os.path.join("instance", "economy_agent_v2.db"))
    if os.path.exists(v2_path):
      try:
        _storage_v2 = SQLiteV2Storage(v2_path)
      except Exception:
        _storage_v2 = None
  return _storage_v2


def set_storage_v2(storage: Optional[SQLiteV2Storage]):
  """Umożliwia wstrzyknięcie izolowanej instancji SQLiteV2Storage (np. w testach)."""
  global _storage_v2
  _storage_v2 = storage


def format_report_html(text: str) -> str:
  """Bezpiecznie formatuje tekst markdown raportu na HTML.

  Stosuje rygorystyczne reguły ochrony przed XSS i formatowania:
  1. Pełna ucieczka znaków specjalnych HTML (escape).
  2. Zamiana nagłówków Markdown (#, ##, ###) na semantyczne tagi HTML (h1, h2, h3).
  3. Formatowanie pogrubień (**tekst** -> <strong>tekst</strong>).
  4. Bezpieczna zamiana odnośników numerycznych [1], [2] na indeksy górne.
  5. Zamiana bezpiecznych linków URL na klikalne hiperłącza z walidacją scheme.
  """
  if not text:
    return ""

  # 1. Escapowanie znaków specjalnych HTML (neutralizuje tagi <script>, <img>, <iframe>, zdarzenia on* itp.)
  text = html.escape(str(text), quote=True)

  # 2. Bezpieczna zamiana nagłówków i akcentów Markdown
  text = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
  text = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
  text = re.sub(r"^#\s+(.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
  text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)

  # 3. Zamiana przypisów [1], [2] na indeks górny
  text = re.sub(
      r"\[(\d+)\]",
      r"<sup style='color:#2980b9; font-weight:bold;'>[\1]</sup>",
      text,
  )

  # 4. Bezpieczna zamiana linków URL na klikalne hiperłącza z walidacją schematu
  def replace_url(match):
    raw_url = match.group(1)
    trailing = ""
    while raw_url and raw_url[-1] in ".,;:!?":
      trailing = raw_url[-1] + trailing
      raw_url = raw_url[:-1]

    parsed = urlparse(raw_url.replace("&amp;", "&"))
    if parsed.scheme in ("http", "https") and parsed.netloc:
      return (
          f'<a href="{raw_url}" target="_blank" rel="noopener noreferrer"'
          f' style="color: #38658F; text-decoration: underline;">{raw_url}</a>{trailing}'
      )
    return match.group(0)

  text = re.sub(r'(https?://[^\s\)<>"\']+)', replace_url, text)

  return text


_LOGO_PATH = Path(__file__).resolve().parent / "static" / "logo.png"
_LOGO_DATA_URI: Optional[str] = None


def get_logo_data_uri() -> str:
  global _LOGO_DATA_URI
  if _LOGO_DATA_URI is None:
    if _LOGO_PATH.exists():
      encoded = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
      _LOGO_DATA_URI = f"data:image/png;base64,{encoded}"
    else:
      _LOGO_DATA_URI = ""
  return _LOGO_DATA_URI


def build_html_template(report_text: str, country: str) -> str:
  safe_country = html.escape(str(country or ""), quote=True)
  formatted_content = format_report_html(report_text)
  logo_uri = get_logo_data_uri()
  logo_css = (
      f'.report-logo {{ background-image: url("{logo_uri}"); background-size: contain; background-repeat: no-repeat; background-position: center; width: 100%; height: 100%; display: block; }}'
      if logo_uri
      else ""
  )
  logo_div = (
      '<div class="logo-card">'
      '<div class="report-logo" role="img" aria-label="Logo"></div>'
      '</div>'
      if logo_uri
      else ""
  )
  return f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raport Kondycji Gospodarczej: {safe_country}</title>
    <style>
        :root {{
            --navy-primary: #142B49;
            --accent-blue: #38658F;
            --bg-light: #F3F6FA;
            --card-white: #FFFFFF;
            --text-dark: #142B49;
            --text-muted: #5A6A80;
            --border-light: #D9E2EC;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            background-color: var(--bg-light);
            color: var(--text-dark);
            line-height: 1.75;
        }}
        .header {{
            background-color: var(--card-white);
            border-bottom: 2px solid var(--border-light);
            padding: 35px 20px 30px 20px;
            text-align: center;
            box-shadow: 0 2px 12px rgba(20, 43, 73, 0.04);
        }}
        .logo-card {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: var(--card-white);
            border: 1px solid var(--border-light);
            border-radius: 16px;
            padding: 12px;
            margin: 0 auto 16px auto;
            box-shadow: 0 4px 14px rgba(20, 43, 73, 0.08);
            width: 96px;
            height: 96px;
        }}
        {logo_css}
        .header h1 {{
            color: var(--navy-primary);
            margin: 0 0 8px 0;
            font-size: 1.85rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }}
        .header p {{
            color: var(--accent-blue);
            margin: 0;
            font-size: 1.05rem;
            font-weight: 500;
        }}
        .container {{
            max-width: 920px;
            margin: 36px auto;
            background: var(--card-white);
            padding: 44px 48px;
            border-radius: 12px;
            border: 1px solid var(--border-light);
            box-shadow: 0 6px 24px rgba(20, 43, 73, 0.06);
        }}
        h1 {{ color: var(--navy-primary); margin-top: 10px; font-size: 1.7rem; font-weight: 700; }}
        h2 {{
            color: var(--navy-primary);
            border-bottom: 2px solid var(--accent-blue);
            padding-bottom: 8px;
            margin-top: 36px;
            margin-bottom: 16px;
            font-size: 1.35rem;
            font-weight: 600;
        }}
        h3 {{ color: var(--accent-blue); margin-top: 24px; margin-bottom: 12px; font-size: 1.15rem; font-weight: 600; }}
        .report-content {{
            font-size: 1.05rem;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        .report-content sup {{
            color: var(--accent-blue);
            font-weight: 700;
            font-size: 0.85em;
            padding: 0 2px;
        }}
        .report-content a {{
            color: var(--accent-blue);
            text-decoration: underline;
            word-break: break-all;
        }}
        .footer {{
            text-align: center;
            margin-top: 48px;
            font-size: 0.9rem;
            color: var(--text-muted);
            border-top: 1px solid var(--border-light);
            padding-top: 24px;
        }}
        @media (max-width: 768px) {{
            .header {{ padding: 24px 16px; }}
            .header h1 {{ font-size: 1.4rem; }}
            .header p {{ font-size: 0.95rem; }}
            .logo-card {{ width: 76px; height: 76px; padding: 8px; }}
            .container {{ margin: 16px 12px; padding: 24px 18px; }}
            h1 {{ font-size: 1.45rem; }}
            h2 {{ font-size: 1.2rem; }}
            h3 {{ font-size: 1.05rem; }}
            .report-content {{ font-size: 0.98rem; }}
        }}
    </style>
</head>
<body>
    <header class="header">
        {logo_div}
        <h1>Autonomiczny System Analizy Makroekonomicznej</h1>
        <p>Raport z weryfikacją wieloźródłową i aparatem krytycznym</p>
    </header>
    <div class="container">
        <div class="report-content">{formatted_content}</div>
        <div class="footer">
            Raport wygenerowany dla kraju: {safe_country}
        </div>
    </div>
</body>
</html>"""


def build_failure_html_template(
    country: str,
    run_id: str,
    reason: str,
    archival_markdown: Optional[str] = None,
) -> str:
  safe_country = html.escape(str(country or ""), quote=True)
  safe_run_id = html.escape(str(run_id or ""), quote=True)
  safe_reason = html.escape(str(reason or ""), quote=True)
  logo_uri = get_logo_data_uri()
  logo_div = (
      '<div class="logo-card">'
      '<div class="report-logo" role="img" aria-label="Logo"></div>'
      '</div>'
      if logo_uri
      else ""
  )

  archival_html = ""
  if archival_markdown:
    formatted_archival = format_report_html(archival_markdown)
    archival_html = f"""
    <section class="archive-section">
        <div class="archive-header">
            <span class="archive-badge">ARCHIWUM</span>
            <h3>Poprzedni poprawny raport historyczny</h3>
            <p>Poniższa treść pochodzi z wcześniejszego pomyślnego wykonania i NIE stanowi wyniku bieżącego przebiegu ({safe_run_id}).</p>
        </div>
        <div class="report-content archival-content">
            {formatted_archival}
        </div>
    </section>
    """

  return f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Niepowodzenie Przebiegu ({safe_run_id}) - Polish Economy Agent</title>
    <style>
        :root {{
            --navy-primary: #142B49;
            --accent-blue: #38658F;
            --bg-light: #F3F6FA;
            --card-white: #FFFFFF;
            --text-dark: #142B49;
            --text-muted: #5A6A80;
            --border-light: #D9E2EC;
            --danger-red: #C0392B;
            --danger-bg: #FDEDEC;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            background-color: var(--bg-light);
            color: var(--text-dark);
            line-height: 1.75;
        }}
        .header {{
            background-color: var(--card-white);
            border-bottom: 2px solid var(--border-light);
            padding: 35px 20px 30px 20px;
            text-align: center;
            box-shadow: 0 2px 12px rgba(20, 43, 73, 0.04);
        }}
        .logo-card {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: var(--card-white);
            border: 1px solid var(--border-light);
            border-radius: 16px;
            padding: 12px;
            margin: 0 auto 16px auto;
            box-shadow: 0 4px 14px rgba(20, 43, 73, 0.08);
            width: 96px;
            height: 96px;
        }}
        .report-logo {{
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
        }}
        .header h1 {{
            color: var(--navy-primary);
            margin: 0 0 8px 0;
            font-size: 1.85rem;
            font-weight: 700;
        }}
        .header p {{
            color: var(--accent-blue);
            margin: 0;
            font-size: 1.05rem;
            font-weight: 500;
        }}
        .container {{
            max-width: 920px;
            margin: 36px auto;
            background: var(--card-white);
            padding: 44px 48px;
            border-radius: 12px;
            border: 1px solid var(--border-light);
            box-shadow: 0 6px 24px rgba(20, 43, 73, 0.06);
        }}
        .failure-card {{
            background: var(--danger-bg);
            border: 1px solid #F5B7B1;
            border-left: 6px solid var(--danger-red);
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .status-badge {{
            display: inline-block;
            background: var(--danger-red);
            color: #FFFFFF;
            font-weight: 700;
            font-size: 0.8rem;
            padding: 4px 10px;
            border-radius: 4px;
            letter-spacing: 0.05em;
            margin-bottom: 12px;
        }}
        .failure-card h2 {{
            color: var(--danger-red);
            margin: 0 0 12px 0;
            font-size: 1.35rem;
            font-weight: 700;
        }}
        .failure-card p {{
            margin: 6px 0;
            font-size: 1rem;
        }}
        .failure-reason-box {{
            background: #FFFFFF;
            border: 1px solid var(--border-light);
            border-radius: 6px;
            padding: 14px 18px;
            margin-top: 14px;
            font-family: monospace;
            font-size: 0.95rem;
            color: #2C3E50;
            word-break: break-all;
        }}
        .archive-section {{
            margin-top: 40px;
            border-top: 2px dashed var(--border-light);
            padding-top: 32px;
        }}
        .archive-badge {{
            display: inline-block;
            background: var(--accent-blue);
            color: #FFFFFF;
            font-size: 0.8rem;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 4px;
            margin-bottom: 6px;
        }}
        .archive-header h3 {{
            color: var(--navy-primary);
            margin: 4px 0 6px 0;
            font-size: 1.25rem;
        }}
        .archive-header p {{
            color: var(--text-muted);
            margin: 0 0 20px 0;
            font-size: 0.95rem;
        }}
        .archival-content {{
            opacity: 0.88;
            background: #FAFCFE;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid var(--border-light);
        }}
        .footer {{
            text-align: center;
            margin-top: 48px;
            font-size: 0.9rem;
            color: var(--text-muted);
            border-top: 1px solid var(--border-light);
            padding-top: 24px;
        }}
        @media (max-width: 768px) {{
            .header {{ padding: 24px 16px; }}
            .header h1 {{ font-size: 1.4rem; }}
            .container {{ margin: 16px 12px; padding: 24px 18px; }}
            .logo-card {{ width: 76px; height: 76px; padding: 8px; }}
        }}
    </style>
</head>
<body>
    <header class="header">
        {logo_div}
        <h1>Autonomiczny System Analizy Makroekonomicznej</h1>
        <p>Status Systemu Analitycznego</p>
    </header>
    <main class="container">
        <section class="failure-card">
            <span class="status-badge">PIPELINE STATUS: FAILED</span>
            <h2>Bieżący przebieg zakończony niepowodzeniem</h2>
            <p><strong>Identyfikator przebiegu (run_id):</strong> <code>{safe_run_id}</code></p>
            <p>Raport dla bieżącego uruchomienia nie został wygenerowany ze względów bezpieczeństwa i integralności danych. W trybie live system nie stosuje zastępczych szablonów deterministycznych.</p>
            <div class="failure-reason-box">
                <strong>Szczegóły niepowodzenia:</strong> {safe_reason}
            </div>
        </section>
        {archival_html}
        <footer class="footer">
            Raport dla kraju: {safe_country}
        </footer>
    </div>
</body>
</html>"""


def get_last_run_path() -> Path:
  return Path("instance") / "logs" / "last_run.json"


def save_report_to_html(report_text: str):
  html_content = build_html_template(report_text, config.DEFAULT_COUNTRY)
  current_dir = os.path.dirname(os.path.abspath(__file__))
  report_path = os.path.join(current_dir, "report.html")
  with open(report_path, "w", encoding="utf-8") as f:
    f.write(html_content)


@server.route("/")
@server.route("/report.html")
def serve_report():
  global _storage_v2, _db
  # Sprawdzenie czy ostatni przebieg zakończył się niepowodzeniem (FAILED)
  last_run_path = get_last_run_path()
  last_run_failed = False
  failed_run_id = None
  failed_reason = None
  if last_run_path.exists():
    try:
      with open(last_run_path, "r", encoding="utf-8") as f:
        run_data = json.load(f)
        if run_data.get("pipeline_status") == "FAILED":
          last_run_failed = True
          failed_run_id = run_data.get("run_id")
          failed_reason = run_data.get("fallback_reason") or "Błąd generowania raportu lub odrzucenie przez walidator"
    except Exception:
      pass

  # Jeśli ostatni przebieg zakończył się FAILED, renderujemy dedykowaną stronę błędu (nigdy nie udajemy, że stary raport jest wynikiem bieżącego uruchomienia)
  if last_run_failed:
    archival_markdown = None
    if _storage_v2 is not None:
      try:
        prev = _storage_v2.get_latest_report(config.DEFAULT_COUNTRY)
        if prev and prev.get("report_markdown"):
          archival_markdown = prev.get("report_markdown")
      except Exception:
        pass
    elif get_storage_v2() is not None:
      try:
        prev = get_storage_v2().get_latest_report(config.DEFAULT_COUNTRY)
        if prev and prev.get("report_markdown"):
          archival_markdown = prev.get("report_markdown")
      except Exception:
        pass

    return build_failure_html_template(
        country=config.DEFAULT_COUNTRY,
        run_id=failed_run_id or "RUN_UNKNOWN",
        reason=failed_reason or "Nieznany błąd potoku",
        archival_markdown=archival_markdown,
    )

  # 1. Jeśli wstrzyknięto izolowaną bazę SQLite v2 (np. w testach v2)
  if _storage_v2 is not None:
    try:
      latest_v2 = _storage_v2.get_latest_report(config.DEFAULT_COUNTRY)
      if latest_v2 and latest_v2.get("report_markdown"):
        return build_html_template(latest_v2["report_markdown"], config.DEFAULT_COUNTRY)
    except Exception as err:
      print(f"[App Warning] Błąd odczytu ze wstrzykniętej bazy v2: {err}")

  # 2. Jeśli wstrzyknięto izolowaną bazę legacy SQLite v1 (np. w testach v1 / html security)
  if _db is not None:
    latest_db_report = _db.get_latest_report(config.DEFAULT_COUNTRY)
    if latest_db_report:
      markdown_content = latest_db_report[2]
      return build_html_template(markdown_content, config.DEFAULT_COUNTRY)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    report_path = os.path.join(current_dir, "report.html")
    if os.path.exists(report_path):
      return send_file(report_path)
    return "Brak wygenerowanego raportu w bazie ani na dysku.", 404

  # 3. Domyślny tryb produkcyjny (brak wstrzykniętych baz testowych)
  storage_v2 = get_storage_v2()
  if storage_v2 is not None:
    try:
      latest_v2 = storage_v2.get_latest_report(config.DEFAULT_COUNTRY)
      if latest_v2 and latest_v2.get("report_markdown"):
        return build_html_template(latest_v2["report_markdown"], config.DEFAULT_COUNTRY)
    except Exception as err:
      print(f"[App Warning] Błąd odczytu z domyślnej bazy v2: {err}")

  database = get_db()
  latest_db_report = database.get_latest_report(config.DEFAULT_COUNTRY)
  if latest_db_report:
    markdown_content = latest_db_report[2]
    return build_html_template(markdown_content, config.DEFAULT_COUNTRY)

  current_dir = os.path.dirname(os.path.abspath(__file__))
  report_path = os.path.join(current_dir, "report.html")
  if os.path.exists(report_path):
    return send_file(report_path)

  return "Brak wygenerowanego raportu w bazie ani na dysku.", 404


def run_pipeline(force_refresh: bool = True, offline_mode: bool = False, use_v2: bool = True):
  country = config.DEFAULT_COUNTRY
  print("=" * 60)
  print(f"Uruchamianie Agenta Ekonomicznego dla kraju: {country}")
  print("=" * 60)

  if use_v2:
    from modules.pipeline_v2 import MacroPipelineV2
    current_dir = os.path.dirname(os.path.abspath(__file__))
    report_path = os.path.join(current_dir, "report.html")
    v2_storage = get_storage_v2() or SQLiteV2Storage()
    pipeline = MacroPipelineV2(db=v2_storage, offline_mode=offline_mode)
    result = pipeline.run(country=country, output_html_path=report_path, force_refresh=force_refresh)
    if result.success:
      print("\n[System] Potok v2 zakończony sukcesem. Podgląd: http://127.0.0.1:5000/report.html\n")
    else:
      print(f"\n[System] Potok v2 zakończony niepowodzeniem (status={result.status}).\n")
    return result

  # Ścieżka legacy (v1)
  database = get_db()
  economic_data = database.get_sources(
      country=country, agent_name="PolishEconomyAgent"
  )
  if not economic_data:
    print("[System] Inicjalizacja listy zaufanych źródeł...")
    checker = PolishEconomySourceChecker()
    checker.populate_initial_sources(country=country)
    economic_data = database.get_sources(
        country=country, agent_name="PolishEconomyAgent"
    )

  evaluator = EconomyEvaluator()
  report_text = evaluator.evaluate_and_compare(country=country)

  save_report_to_html(report_text)
  print("\n[System] Raport wygenerowany. Podgląd: http://127.0.0.1:5000/report.html\n")


if __name__ == "__main__":
  run_pipeline(force_refresh=True)
  server.run(host="127.0.0.1", port=5000, debug=False)
