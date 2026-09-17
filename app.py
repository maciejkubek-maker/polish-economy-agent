import os
import re
import config
from flask import Flask, render_template_string, send_file
from modules.data_fetcher import EconomyDataFetcher
from modules.database import EconomyDatabase
from modules.evaluator import EconomyEvaluator
from modules.gpt_fetcher import OpenAIDataFetcher
from modules.search_service import WebSearchService
from modules.sources import PolishEconomySourceChecker

server = Flask(__name__)
db = EconomyDatabase()
latest_report_text = ""


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


def save_report_to_html(report_text: str):
  formatted_content = format_report_html(report_text)

  html_content = f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Raport Kondycji Gospodarczej: {config.DEFAULT_COUNTRY}</title>
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
            Raport wygenerowany dla kraju: {config.DEFAULT_COUNTRY}
        </div>
    </div>
</body>
</html>"""
  current_dir = os.path.dirname(os.path.abspath(__file__))
  report_path = os.path.join(current_dir, "report.html")
  with open(report_path, "w", encoding="utf-8") as f:
    f.write(html_content)


@server.route("/")
@server.route("/report.html")
def serve_report():
  current_dir = os.path.dirname(os.path.abspath(__file__))
  report_path = os.path.join(current_dir, "report.html")
  if os.path.exists(report_path):
    return send_file(report_path)
  return "Brak pliku report.html", 404


def run_pipeline():
  global latest_report_text
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

  if db.are_indicators_fresh(country=country, max_days=3):
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
  latest_report_text = evaluator.evaluate_and_compare(country=country)
  save_report_to_html(latest_report_text)
  print("\n[System] Raport został pomyślnie wygenerowany i zapisany.")
  print("Podgląd: http://127.0.0.1:5000/report.html\n")


if __name__ == "__main__":
  run_pipeline()
  server.run(host="127.0.0.1", port=5000, debug=False)