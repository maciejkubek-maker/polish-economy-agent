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
  return text


def save_report_to_html(report_text: str):
  formatted_content = format_report_html(report_text)

  html_content = f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Raport Kondycji Gospodarczej: {config.DEFAULT_COUNTRY}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; background-color: #f4f6f9; color: #333; }}
        .header {{ background-color: #2c3e50; color: white; padding: 30px 40px; text-align: center; }}
        .container {{ max-width: 900px; margin: 30px auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
        h1, h2, h3 {{ color: #2c3e50; margin-top: 25px; }}
        h2 {{ border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
        .report-content {{ line-height: 1.7; white-space: pre-wrap; font-size: 1.05em; background: #fafbfc; padding: 30px; border-left: 4px solid #3498db; border-radius: 4px; margin-top: 20px; }}
        .footer {{ text-align: center; margin-top: 40px; font-size: 0.9em; color: #7f8c8d; border-top: 1px solid #eee; padding-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Autonomiczny System Analizy Makroekonomicznej</h1>
        <p>Raport analityczny z weryfikacją wieloźródłową</p>
    </div>
    <div class="container">
        <h2>Szczegółowy Raport Analityczny</h2>
        <div class="report-content">{formatted_content}</div>
        <div class="footer">
            Raport wygenerowany przez System Agenta Ekonomicznego &bull; Kraj: {config.DEFAULT_COUNTRY}
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
  return (
      "Plik report.html nie został odnaleziony. Uruchom najpierw potok"
      " analityczny.",
      404,
  )


@server.route("/report-details")
def serve_report_details():
  global latest_report_text
  return render_template_string(
      "<!DOCTYPE html><html><head><meta"
      " charset='UTF-8'><title>Raport</title></head><body"
      " style='font-family:Arial; margin:40px;'><pre"
      " style='white-space:pre-wrap;'>{{ report }}</pre></body></html>",
      report=latest_report_text,
  )


def run_pipeline():
  global latest_report_text
  country = config.DEFAULT_COUNTRY
  print("=" * 60)
  print(f"Uruchamianie Agenta Ekonomicznego dla kraju: {country}")
  print("=" * 60)

  # Sprawdzenie źródeł
  economic_data = db.get_sources(
      country=country, agent_name="PolishEconomyAgent"
  )
  if not economic_data:
    print("[LLM] Inicjalizacja bazy zaufanych źródeł...")
    checker = PolishEconomySourceChecker()
    economic_data = checker.get_trusted_sources(country=country)
    db.save_sources(economic_data, agent_name="PolishEconomyAgent")

  # Sprawdzenie świeżości danych (domyślnie max 3 dni)
  if db.are_indicators_fresh(country=country, max_days=3):
    print(
        f"[Cache] Dane dla {country} są aktualne (z ostatnich 3 dni). Pomijam"
        " pobieranie przez Tavily i agentów."
    )
  else:
    print(f"[System] Pobieranie nowych wskaźników dla kraju: {country}...")

    # Jednorazowe zapytanie do Tavily
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

  # Generowanie raportu
  evaluator = EconomyEvaluator()
  latest_report_text = evaluator.evaluate_and_compare(country=country)
  save_report_to_html(latest_report_text)
  print("[System] Wygenerowano i zapisano raport do pliku report.html.")

  print("\n" + "=" * 60)
  print("RAPORT GOSPODARCZY")
  print("=" * 60)
  print(latest_report_text)
  print("\n" + "-" * 60)
  print("Serwer HTTP uruchomiony. Link podglądu:")
  print("http://127.0.0.1:5000/report.html")
  print("-" * 60)


if __name__ == "__main__":
  run_pipeline()
  server.run(host="127.0.0.1", port=5000, debug=False)