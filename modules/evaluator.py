import sqlite3
import config
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI


class EconomyEvaluator:

  def __init__(self):
    self.db_path = "instance/economy_agent.db"
    self.llm = ChatGoogleGenerativeAI(
        model=config.DEFAULT_LLM_MODEL,
        google_api_key=config.GOOGLE_API_KEY,
        temperature=0.2,
    )

  def fetch_data_for_comparison(self, country: str):
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
            SELECT agent_name, indicator_name, value, period, source_name, page_info, created_at 
            FROM collected_indicators 
            WHERE country = ? 
            ORDER BY period DESC, created_at DESC
        """,
        (country,),
    )
    rows = cursor.fetchall()
    conn.close()

    gemini_records = [r for r in rows if r[0] == "GeminiAgent"]
    gpt_records = [r for r in rows if r[0] == "GPTAgent"]

    return gemini_records, gpt_records

  def evaluate_and_compare(self, country: str):
    gemini_records, gpt_records = self.fetch_data_for_comparison(country)

    if not gemini_records or not gpt_records:
      raise ValueError(
          "Brak danych w bazie od obu agentów. Uruchom najpierw pobieranie"
          " danych."
      )

    gemini_text = "\n".join(
        [f"- [{r[3]}] {r[1]}: {r[2]} (Źródło: {r[4]})" for r in gemini_records]
    )
    gpt_text = "\n".join(
        [f"- [{r[3]}] {r[1]}: {r[2]} (Źródło: {r[4]})" for r in gpt_records]
    )

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            (
                "Jesteś Głównym Analitykiem Ekonomicznym i Bezkompromisowym"
                " Doradcą Finansowym.\n"
                "Otrzymujesz strumienie danych rynkowych i historycznych dla"
                " podanego kraju.\n\n"
                "TWOJE ZADANIE:\n"
                "1. Przeprowadź rygorystyczną weryfikację i przeanalizuj"
                " dostępne dane i trendy dla kluczowych wskaźników (PKB,"
                " Inflacja, Stopa bezrobocia, Płace).\n"
                "2. ZLOKALIZUJ ZAGROŻENIA I NEGATYWNE TRENDY: Nie upiększaj"
                " rzeczywistości! Jeśli wskaźniki pogarszają się, rośnie"
                " bezrobocie, inflacja utrzymuje się na uporczywie wysokim"
                " poziomie lub PKB zwalnia, wprost i bezwzględnie wskaż te"
                " negatywne zjawiska oraz ryzyka.\n"
                "3. Przygotuj obiektywny, krytyczny i realistyczny raport"
                " gospodarczy (bez sztucznego optymizmu).\n\n"
                "ŚCISŁE ZASADY:\n"
                "- BEZWZGLĘDNIE ZAKAZANE jest pisanie o 'Agentach', 'Gemini',"
                " 'GPT', 'halucynacjach' czy technicznych kulisach AI.\n"
                "- Pisz zwięźle, konkretnie i z zachowaniem pełnego obiektywizmu"
                " (pokaż zarówno plusy, jak i realne zagrożenia oraz negatywne"
                " trendy).\n\n"
                "STRUKTURA RAPORTU:\n"
                "# RAPORT KONDYCJI GOSPODARCZEJ: {country}\n\n"
                "## 1. Analiza Trendów w Dostępnym Okresie\n"
                "## 2. Zagrożenia i Ryzyka Makroekonomiczne\n"
                "## 3. Co to oznacza dla Kowalskiego? (Perspektywa"
                " Obywatela)\n"
                "- **Kredyty i Raty:** (wpływ stóp procentowych)\n"
                "- **Ceny i Zakupy:** (siła nabywcza)\n"
                "- **Praca i Zarobki:** (stabilność zatrudnienia i płac)\n\n"
                "## 4. Co to oznacza dla Przedsiębiorców?\n"
                "## 5. Podsumowanie i Realistyczny Werdykt"
            ),
        ),
        (
            "human",
            "Kraj: {country}\n\n"
            "--- DANE ŹRÓDŁOWE STRUMIEŃ A ---\n{gemini_text}\n\n"
            "--- DANE ŹRÓDŁOWE STRUMIEŃ B ---\n{gpt_text}\n\n"
            "Przygotuj kompletny, krytyczny raport uwzględniający nadesłane dane historyczne.",
        ),
    ])

    chain = prompt | self.llm | StrOutputParser()

    print(
        "\n[Evaluator] Generowanie zaawansowanego raportu na podstawie danych z"
        " bazy..."
    )
    response = chain.invoke({
        "country": country,
        "gemini_text": gemini_text,
        "gpt_text": gpt_text,
    })

    return response