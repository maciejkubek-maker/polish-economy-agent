import sqlite3
import config
from langchain_core.callbacks import StreamingStdOutCallbackHandler
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


class EconomyEvaluator:

  def __init__(self):
    self.db_path = "instance/economy_agent.db"

  def fetch_data_for_comparison(self, country: str):
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
            SELECT agent_name, indicator_name, value, period, source_name, page_info, created_at 
            FROM collected_indicators 
            WHERE country = ? 
            ORDER BY id DESC
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

    if not gemini_records and not gpt_records:
      raise ValueError("Brak danych w bazie. Uruchom najpierw pobieranie.")

    stream_a = "\n".join([
        f"- {r[1]}: {r[2]} (Okres: {r[3]}) | Źródło: {r[4]} | Adres/Szczegóły:"
        f" {r[5]}"
        for r in gemini_records
    ])
    stream_b = "\n".join([
        f"- {r[1]}: {r[2]} (Okres: {r[3]}) | Źródło: {r[4]} | Adres/Szczegóły:"
        f" {r[5]}"
        for r in gpt_records
    ])

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            (
                "Jesteś Głównym Analitykiem Ekonomicznym i Doradcą Finansowym.\n"
                "Na podstawie nadesłanych danych przygotuj rygorystyczny,"
                " krytyczny raport gospodarczy dla wskazanego kraju.\n\n"
                "ZASADY PRZYPISÓW I ŹRÓDEŁ:\n"
                "1. Każda podana liczba, wskaźnik, prognoza czy fakt MUSI mieć"
                " przypisany numeryczny odnośnik w tekście, np. [1], [2].\n"
                "2. Na końcu raportu zamieść sekcję '6. Źródła danych i"
                " Metodologia' z pełnym wykazem numerów, nazwą instytucji oraz"
                " bezpośrednim adresem URL wyciągniętym z danych wejściowych.\n"
                "3. Jeśli wskaźniki pokazują negatywne zjawiska (np. spadek"
                " PMI, wysoka inflacja, wysoki koszt pieniądza), wskaż je"
                " wprost i bez upiększania.\n"
                "4. BEZWZGLĘDNY ZAKAZ wspominania o 'Agentach', 'Gemini',"
                " 'GPT', sztucznej inteligencji czy modelach językowych.\n\n"
                "STRUKTURA DOKUMENTU:\n"
                "# RAPORT KONDYCJI GOSPODARCZEJ: {country}\n\n"
                "## 1. Analiza Trendów w Dostępnym Okresie\n"
                "## 2. Zagrożenia i Ryzyka Makroekonomiczne\n"
                "## 3. Co to oznacza dla Kowalskiego? (Perspektywa"
                " Obywatela)\n"
                "- **Kredyty i Raty:** (wpływ stóp procentowych)\n"
                "- **Ceny i Zakupy:** (siła nabywcza)\n"
                "- **Praca i Zarobki:** (stabilność zatrudnienia i płac)\n\n"
                "## 4. Co to oznacza dla Przedsiębiorców?\n"
                "## 5. Podsumowanie i Realistyczny Werdykt\n"
                "## 6. Źródła danych i Metodologia\n"
                "(Lista odnośników: [1] Instytucja / Źródło – URL (okres"
                " danych))"
            ),
        ),
        (
            "human",
            "Kraj: {country}\n\n"
            "--- ZESTAW DANYCH WERYFIKACYJNYCH A ---\n{stream_a}\n\n"
            "--- ZESTAW DANYCH WERYFIKACYJNYCH B ---\n{stream_b}\n\n"
            "Sporządź kompletny, krytyczny raport makroekonomiczny z"
            " przypisami.",
        ),
    ])

    inputs = {"country": country, "stream_a": stream_a, "stream_b": stream_b}

    print(
        "\n[Evaluator] Generowanie raportu z przypisami (strumieniowanie na"
        " żywo):\n"
    )

    try:
      llm_gemini = ChatGoogleGenerativeAI(
          model=config.DEFAULT_LLM_MODEL,
          google_api_key=config.GOOGLE_API_KEY,
          streaming=True,
          callbacks=[StreamingStdOutCallbackHandler()],
      )
      chain = prompt | llm_gemini | StrOutputParser()
      return chain.invoke(inputs)
    except Exception as err:
      print(
          f"\n[Evaluator Notice] Przełączam awaryjnie na GPT-4o (powód:"
          f" {err})...\n"
      )
      llm_gpt = ChatOpenAI(
          model=config.DEFAULT_OPENAI_MODEL,
          api_key=config.OPENAI_API_KEY,
          streaming=True,
          callbacks=[StreamingStdOutCallbackHandler()],
          temperature=0.2,
      )
      chain_gpt = prompt | llm_gpt | StrOutputParser()
      return chain_gpt.invoke(inputs)