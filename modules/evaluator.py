from collections import defaultdict
import datetime
import re
import sqlite3
import config
from langchain_core.callbacks import StreamingStdOutCallbackHandler
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


def build_executive_horizon(raw_periods: list[str]) -> str:
  months_found = set()
  quarters_found = set()
  years_found = set()

  month_names = {
      1: "styczeń",
      2: "luty",
      3: "marzec",
      4: "kwiecień",
      5: "maj",
      6: "czerwiec",
      7: "lipiec",
      8: "sierpień",
      9: "wrzesień",
      10: "październik",
      11: "listopad",
      12: "grudzień",
  }

  roman_to_month = {
      "i": 1,
      "ii": 2,
      "iii": 3,
      "iv": 4,
      "v": 5,
      "vi": 6,
      "vii": 7,
      "viii": 8,
      "ix": 9,
      "x": 10,
      "xi": 11,
      "xii": 12,
  }
  roman_to_q = {"i": "I", "ii": "II", "iii": "III", "iv": "IV"}

  for raw in raw_periods:
    if not raw or str(raw).strip().lower() in ("brak danych", "none", ""):
      continue
    p = str(raw).lower().strip()

    y_match = re.search(r"(20\d{2})", p)
    year = int(y_match.group(1)) if y_match else None
    if year:
      years_found.add(year)

    q_match = re.search(r"(i{1,3}|iv|q[1-4])\s*(?:kw\.?|kwartał)", p)
    if q_match and year:
      token = q_match.group(1).replace("q", "").lower()
      q_label = (
          f"{roman_to_q.get(token, token.upper())} kw. {year}"
          if token in roman_to_q
          else f"{token.upper()} kw. {year}"
      )
      quarters_found.add(q_label)
      continue

    m_num = None
    for r_str, num in roman_to_month.items():
      if re.search(rf"\b{r_str}\b", p):
        m_num = num
        break

    if not m_num:
      for num, m_name in month_names.items():
        if m_name in p:
          m_num = num
          break

    if not m_num:
      num_match = re.search(r"\b(0?[1-9]|1[0-2])\b[\.\/\-]", p)
      if num_match:
        m_num = int(num_match.group(1))

    if m_num and year:
      months_found.add((year, m_num))

  parts = []

  if months_found:
    sorted_months = sorted(list(months_found), key=lambda x: (x[0], x[1]))
    latest_year = sorted_months[-1][0]
    latest_year_months = [m for y, m in sorted_months if y == latest_year]

    if len(latest_year_months) >= 2:
      m_start = month_names[latest_year_months[-2]]
      m_end = month_names[latest_year_months[-1]]
      parts.append(
          f"{m_start.capitalize()} – {m_end} {latest_year} (wskaźniki"
          " miesięczne)"
      )
    else:
      m_single = month_names[latest_year_months[-1]]
      parts.append(f"{m_single.capitalize()} {latest_year} (dane miesięczne)")

  if quarters_found:
    latest_q = sorted(list(quarters_found))[-1]
    parts.append(f"{latest_q} (PKB)")

  if years_found:
    past_years = [y for y in sorted(list(years_found)) if y < max(years_found)]
    if past_years:
      parts.append(f"baza odniesienia: {', '.join(map(str, past_years))} r.")

  return " | ".join(parts) if parts else "Bieżące odczyty GUS i NBP"


class EconomyEvaluator:

  def __init__(self):
    self.db_path = "instance/economy_agent.db"

  def fetch_timeline_data(self, country: str):
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
            SELECT indicator_name, period, value, previous_value, trend_direction, source_name, page_info, agent_name, created_at 
            FROM collected_indicators 
            WHERE country = ? 
            ORDER BY indicator_name ASC, created_at ASC
        """,
        (country,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
      return {}, []

    indicators_by_name = defaultdict(list)
    for r in rows:
      indicators_by_name[r[0]].append({
          "period": r[1],
          "value": r[2],
          "previous_value": r[3] if len(r) > 3 else "Brak danych",
          "trend_direction": r[4] if len(r) > 4 else "brak danych",
          "source": r[5] if len(r) > 5 else r[3],
          "url": r[6] if len(r) > 6 else r[4],
          "agent": r[7] if len(r) > 7 else r[5],
      })

    return indicators_by_name, rows

  def evaluate_and_compare(self, country: str):
    timeline_map, all_rows = self.fetch_timeline_data(country)

    if not all_rows:
      raise ValueError("Brak danych w bazie. Uruchom najpierw pobieranie.")

    now = datetime.datetime.now()
    report_date = now.strftime("%d.%m.%Y")

    raw_periods = [r[1] for r in all_rows]
    periods_summary = build_executive_horizon(raw_periods)

    timeline_blocks = []
    for ind_name, points in timeline_map.items():
      points_text = "\n".join([
          f"  * Okres: {p['period']} | Wartość: {p['value']} | Poprzednio:"
          f" {p['previous_value']} | Kierunek: {p['trend_direction']} | Źródło:"
          f" {p['source']} ({p['url']})"
          for p in points
      ])
      timeline_blocks.append(f"Wskaźnik: {ind_name}\n{points_text}")

    chronological_context = "\n\n".join(timeline_blocks)

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            (
                "Jesteś Głównym Ekonomistą wiodącej instytucji analitycznej.\n"
                "Data sporządzenia analizy: {report_date}.\n"
                "Skonsolidowany horyzont odczytów: {periods_summary}.\n\n"
                "RYGORYSTYCZNE ZASADY METODOLOGICZNE I EKONOMETRYCZNE:\n"
                "1. ASYNCHRONICZNOŚĆ WSKAŹNIKÓW (LAGI): Wyjaśnij we wstępie,"
                " że wskaźniki spływają z różną częstotliwością (PKB"
                " kwartalnie, koniunktura, inflacja i rynek pracy miesięcznie)"
                " – synteza polega na łączeniu najświeższych dostępnych"
                " odczytów.\n"
                "2. KORELACJA CYKLU INWESTYCYJNEGO: Bezwzględnie syntetyzuj"
                " fakty. Zbieżność spadku PMI (poniżej progu równowagi 50 pkt)"
                " z ujemną dynamiką produkcji budowlano-montażowej oraz"
                " narastającą liczbą bezrobotnych traktuj jako twardy dowód"
                " wygasania cyklu inwestycyjnego w sekcjach 1, 2 i 4.\n"
                "3. METODOLOGIA RYNKU PRACY I PŁAC:\n"
                "   - DIVERGENCE TEST (WOLUMEN VS STOPA): Zawsze weryfikuj"
                " relację stopy bezrobocia (%) do wolumenu bezrobotnych (tys."
                " osób). Jeśli stopa stoi w miejscu na skutek zaokrąglenia"
                " statystycznego, a wolumen osób bez pracy rośnie, ZAKAZUJE SIĘ"
                " nazywania tego 'pozytywnym sygnałem' lub 'stabilizacją' –"
                " definiuj to jako ukryte pogorszenie koniunktury.\n"
                "   - ANOMALIA SEZONOWA: Miesiące letnie to szczyt prac"
                " sezonowych. Brak spadku bezrobocia w tym oknie to negatywna"
                " anomalia cyklu.\n"
                "   - WYNAGRODZENIA A PŁACE REALNE: Zakaz interpretowania"
                " miesięcznych wahań przeciętnego wynagrodzenia (m/m) jako"
                " trwałego spadku dochodów gospodarstw domowych – są to"
                " efekty zmienności premiowej. Ocenę dochodów opieraj wyłącznie"
                " na relacji dynamiki rocznej (r/r) do inflacji CPI (wzrost"
                " bądź erozja płac realnych).\n"
                "4. STOPY PROCENTOWE I POLITYKA MONETARNA: Interpretuj decyzje"
                " banku centralnego przez pryzmat realnej stopy procentowej"
                " (stopa referencyjna minus inflacja CPI). Wskaż, czy bank"
                " centralny ma przestrzeń do stymulacji fiskalno-monetarnej"
                " przy obecnej dynamice cen.\n"
                "5. ZAKAZ BANALNYCH PODSUMOWAŃ: W Sekcji 5 kategorycznie zakazuje"
                " się urzędniczych komunałów (np. 'wymaga uwagi decydentów',"
                " 'należy bacznie obserwować', 'czas pokaże'). Wymagany jest"
                " asertywny, twardy werdykt koniunkturalny: diagnoza ryzyka"
                " stagflacyjnego, stan inwestycji prywatnych oraz perspektywa"
                " rynku pracy na najbliższy kwartał.\n"
                "6. DYSCYPLINA ŹRÓDEŁ: Każda pojedyncza liczba w tekście MUSI"
                " posiadać odnośnik numeryczny (np. [1], [2]), w 100% spójny z"
                " wykazem w sekcji 6.\n"
                "7. Całkowity zakaz odwołań do AI, promptów, modeli czy"
                " skryptów.\n\n"
                "STRUKTURA RAPORTU:\n"
                "# RAPORT KONDYCJI GOSPODARCZEJ: {country}\n"
                "**Data publikacji analizy:** {report_date}  \n"
                "**Horyzont analizowanych danych:** {periods_summary}\n\n"
                "## 1. Analiza Trendów w Dostępnym Okresie\n"
                "## 2. Zagrożenia i Ryzyka Makroekonomiczne\n"
                "## 3. Co to oznacza dla Kowalskiego? (Perspektywa Obywatela)\n"
                "- **Kredyty i Raty:**\n"
                "- **Ceny i Zakupy:**\n"
                "- **Praca i Zarobki:**\n\n"
                "## 4. Co to oznacza dla Przedsiębiorców?\n"
                "## 5. Podsumowanie i Realistyczny Werdykt\n"
                "## 6. Źródła danych i Metodologia\n"
            ),
        ),
        (
            "human",
            "Kraj: {country}\n\n"
            "ZESTAW WSKAŹNIKÓW I HISTORII ODCZYTÓW:\n"
            "{chronological_context}\n\n"
            "Sporządź kompletny, rygorystyczny raport makroekonomiczny z"
            " aparatem krytycznym.",
        ),
    ])

    inputs = {
        "country": country,
        "report_date": report_date,
        "periods_summary": periods_summary,
        "chronological_context": chronological_context,
    }

    print(
        f"\n[Evaluator] Generowanie raportu (Stan na: {report_date} | Horyzont:"
        f" {periods_summary}):\n"
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
          f"\n[Evaluator Notice] Przełączanie awaryjne na model OpenAI: {err}\n"
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