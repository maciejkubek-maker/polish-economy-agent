import datetime
import os
import re
import config
from flask import Flask, send_file
from modules.data_fetcher import EconomyDataFetcher
from modules.database import EconomyDatabase
from modules.evaluator import EconomyEvaluator
from modules.gpt_fetcher import OpenAIDataFetcher
from modules.search_service import WebSearchService
from modules.sources import PolishEconomySourceChecker

server = Flask(__name__)
db = EconomyDatabase()


def format_report_html(text: str) -> str:
  if not text:
    return ""

  text = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
  text = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
  text = re.sub(r"^#\s+(.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
  text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)

  # Zamiana przypisów [1], [2] na indeks górny
  text = re.sub(
      r"\[(\d+)\]",
      r"<sup style='color:#2980b9; font-weight:bold;'>[\1]</sup>",
      text,
  )

  # Zamiana linków URL na klikalne hiperłącza
  text = re.sub(
      r'(https?://[^\s\)<>"]+)',
      r'<a href="\1" target="_blank" rel="noopener noreferrer" style="color:'
      r' #3498db; text-decoration: underline;">\1</a>',
      text,
  )

  return text


def build_html_template(report_text: str, country: str) -> str:
  formatted_content = format_report_html(report_text)
  return f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Raport Kondycji Gospodarczej: {country}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; margin: 0; background-color: #f4f6f9; color: #2c3e50; }}
        .header {{ background-color: #1a252f; color: white; padding: 30px 40px; text-align: center; }}
        .container {{ max-width: 950px; margin: 30px auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
        h1 {{ color: #1a252f; margin-top: 10px; }}
        h2 {{ color: #2980b9; border-bottom: 2px solid #ecf0f1; padding-bottom: 8px; margin-top: 30px; }}
        .report-content {{ line-height: 1.8; white-space: pre-wrap; font-size: 1.05em; background: #ffffff; padding: 10px 0; }}
        .footer {{ text-align: center; margin-top: 40px; font-size: 0.9em; color: #7f8c8d; border-top: 1px solid #eee; padding-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Autonomiczny System Analizy Makroekonomicznej</h1>
        <p>Raport z weryfikacją wieloźródłową i aparatem krytycznym</p>
    </div>
    <div class="container">
        <div class="report-content">{formatted_content}</div>
        <div class="footer">
            Raport wygenerowany dla kraju: {country}
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
  # 1. Pobranie z bazy danych
  latest_db_report = db.get_latest_report(config.DEFAULT_COUNTRY)
  if latest_db_report:
    # latest_db_report: 0: report_date, 1: periods_summary, 2: content_markdown, 3: created_at
    markdown_content = latest_db_report[2]
    return build_html_template(markdown_content, config.DEFAULT_COUNTRY)

  # 2. Awaryjny fallback do pliku na dysku
  current_dir = os.path.dirname(os.path.abspath(__file__))
  report_path = os.path.join(current_dir, "report.html")
  if os.path.exists(report_path):
    return send_file(report_path)

  return "Brak wygenerowanego raportu w bazie ani na dysku.", 404


def run_pipeline(force_refresh: bool = True):
  country = config.DEFAULT_COUNTRY
  print("=" * 60)
  print(f"Uruchamianie Agenta Ekonomicznego dla kraju: {country}")
  print("=" * 60)

  economic_data = db.get_sources(
      country=country, agent_name="PolishEconomyAgent"
  )
  if not economic_data:
    print("[System] Inicjalizacja listy zaufanych źródeł...")
    checker = PolishEconomySourceChecker()
    economic_data = checker.get_trusted_sources(country=country)
    db.save_sources(economic_data, agent_name="PolishEconomyAgent")

  if not force_refresh and db.are_indicators_fresh(
      country=country, max_days=3
  ):
    print(f"[Cache] Dane dla {country} są aktualne. Generowanie raportu...")
  else:
    print(f"[System] Pobieranie nowych wskaźników dla kraju: {country}...")
    search_service = WebSearchService()
    web_results = search_service.search_indicators(country=country)

    gemini_fetcher = EconomyDataFetcher(agent_name="GeminiAgent")
    gemini_fetcher.fetch_and_store_indicators(
        country=country, web_results=web_results
    )

    gpt_fetcher = OpenAIDataFetcher(agent_name="GPTAgent")
    gpt_fetcher.fetch_and_store_indicators(
        country=country, web_results=web_results
    )

  evaluator = EconomyEvaluator()
  report_text = evaluator.evaluate_and_compare(country=country)

  # Zapis lokalny HTML
  save_report_to_html(report_text)

  # Zapis trwały w bazie SQLite
  today_str = datetime.datetime.now().strftime("%d.%m.%Y")
  db.save_generated_report(
      country=country,
      report_date=today_str,
      periods_summary="Najnowsze dostępne odczyty",
      markdown_text=report_text,
  )

  print(
      "\n[System] Raport został pomyślnie zarchiwizowany w bazie danych i"
      " zapisany do HTML."
  )
  print("Podgląd: http://127.0.0.1:5000/report.html\n")


if __name__ == "__main__":
  run_pipeline()
  port = int(os.environ.get("PORT", 5000))
  server.run(host="0.0.0.0", port=port, debug=False)