"""
Aplikacja Polish Economy Agent.
Uruchamia potok danych makroekonomicznych v2 oraz serwuje raport analityczny.
"""

import base64
from datetime import datetime
import html
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
          f' style="color: #3498db; text-decoration: underline;">{raw_url}</a>{trailing}'
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
      f'.report-logo {{ background-image: url("{logo_uri}"); background-size: contain; background-repeat: no-repeat; background-position: center; height: 80px; margin: 0 auto 15px auto; max-width: 300px; }}'
      if logo_uri
      else ""
  )
  logo_div = (
      '<div class="report-logo" role="img" aria-label="Logo"></div>'
      if logo_uri
      else ""
  )
  return f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Raport Kondycji Gospodarczej: {safe_country}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; margin: 0; background-color: #f4f6f9; color: #2c3e50; }}
        .header {{ background-color: #1a252f; color: white; padding: 30px 40px; text-align: center; }}
        {logo_css}
        .container {{ max-width: 950px; margin: 30px auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
        h1 {{ color: #1a252f; margin-top: 10px; }}
        h2 {{ color: #2980b9; border-bottom: 2px solid #ecf0f1; padding-bottom: 8px; margin-top: 30px; }}
        .report-content {{ line-height: 1.8; white-space: pre-wrap; font-size: 1.05em; background: #ffffff; padding: 10px 0; }}
        .footer {{ text-align: center; margin-top: 40px; font-size: 0.9em; color: #7f8c8d; border-top: 1px solid #eee; padding-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        {logo_div}
        <h1>Autonomiczny System Analizy Makroekonomicznej</h1>
        <p>Raport z weryfikacją wieloźródłową i aparatem krytycznym</p>
    </div>
    <div class="container">
        <div class="report-content">{formatted_content}</div>
        <div class="footer">
            Raport wygenerowany dla kraju: {safe_country}
        </div>
    </div>
</body>
</html>"""


def save_report_to_html(report_text: str):
  html_content = build_html_template(report_text, config.DEFAULT_COUNTRY)
  current_dir = os.path.dirname(os.path.abspath(__file__))
  report_path = os.path.join(current_dir, "report.html")
  with open(report_path, "w", encoding="utf-8") as f:
    f.write(html_content)


@server.route("/")
@server.route("/report.html")
def serve_report():
  # 1. Jeśli wstrzyknięto izolowaną bazę SQLite v2 (np. w testach v2)
  global _storage_v2, _db
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
    # Jeśli wstrzyknięto _db, ale brak w niej raportu - sprawdź fallback do pliku
    current_dir = os.path.dirname(os.path.abspath(__file__))
    report_path = os.path.join(current_dir, "report.html")
    if os.path.exists(report_path):
      return send_file(report_path)
    return "Brak wygenerowanego raportu w bazie ani na dysku.", 404

  # 3. Domyślny tryb produkcyjny (brak wstrzykniętych baz testowych)
  # Priorytet 1: Baza SQLite v2 na dysku
  storage_v2 = get_storage_v2()
  if storage_v2 is not None:
    try:
      latest_v2 = storage_v2.get_latest_report(config.DEFAULT_COUNTRY)
      if latest_v2 and latest_v2.get("report_markdown"):
        return build_html_template(latest_v2["report_markdown"], config.DEFAULT_COUNTRY)
    except Exception as err:
      print(f"[App Warning] Błąd odczytu z domyślnej bazy v2: {err}")

  # Priorytet 2: Baza legacy SQLite v1 na dysku
  database = get_db()
  latest_db_report = database.get_latest_report(config.DEFAULT_COUNTRY)
  if latest_db_report:
    markdown_content = latest_db_report[2]
    return build_html_template(markdown_content, config.DEFAULT_COUNTRY)

  # Priorytet 3: Plik HTML na dysku
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
  report_text = evaluator.evaluate(
      country=country,
      economic_data=economic_data,
      force_refresh=force_refresh,
  )

  save_report_to_html(report_text)
  print("\n[System] Raport wygenerowany. Podgląd: http://127.0.0.1:5000/report.html\n")


if __name__ == "__main__":
  run_pipeline(force_refresh=True)
  server.run(host="127.0.0.1", port=5000, debug=False)
