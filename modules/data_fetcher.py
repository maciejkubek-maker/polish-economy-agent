from typing import List, Optional
import config
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from modules.database import EconomyDatabase
from pydantic import BaseModel, Field


class IndicatorItem(BaseModel):
  indicator_name: str = Field(
      description=(
          "Precyzyjna nazwa wskaźnika (np. Stopa bezrobocia, Liczba"
          " zarejestrowanych bezrobotnych, Inflacja CPI r/r, PKB r/r)"
      )
  )
  value: str = Field(description="Bieżąca wartość z jednostką (np. 5.80%, 906.4 tys., 3.90%)")
  period: str = Field(description="Okres odczytu (np. VII 2026, II kw. 2026)")
  previous_value: Optional[str] = Field(
      default="Brak danych",
      description="Wartość z poprzedniego okresu (m/m) lub analogicznego okresu roku ubiegłego (r/r)",
  )
  trend_direction: str = Field(
      description="Kierunek dynamiki: 'wzrost', 'spadek', 'stabilizacja' lub 'brak danych'"
  )
  source_name: str = Field(description="Nazwa instytucji emitującej dane (np. GUS, NBP)")
  page_info: str = Field(description="Bezpośredni adres URL źródła")


class IndicatorResponse(BaseModel):
  country: str
  indicators: List[IndicatorItem]


EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        (
            "Jesteś rygorystycznym analitykiem danych makroekonomicznych ({agent_name}).\n"
            "Twoim jedynym celem jest bezbłędna, literalna ekstrakcja twardych wskaźników z komunikatów prasowych.\n\n"
            "ZASADY PRECYZJI I ANTY-HALUCYNACJI:\n"
            "1. ROZDZIELENIE WSKAŹNIKÓW: Traktuj 'Stopę bezrobocia rejestrowanego (GUS)', 'Stopę bezrobocia (BAEL/Eurostat)' "
            "oraz 'Liczbę zarejestrowanych bezrobotnych' jako ODRĘBNE wskaźniki. Kategoryczny zakaz ich łączenia!\n"
            "2. WARTOŚĆ POPRZEDNIA: Pobieraj punkt odniesienia (previous_value) WYŁĄCZNIE wtedy, gdy autor artykułu "
            "podał go wprost w tekście dla tego samego wskaźnika (np. 'wzrosła z 5,0% do 5,8%'). "
            "Jeśli wartości bazowej nie ma w tekście – wpisz 'Brak danych' i trend 'brak danych'.\n"
            "3. BEZWZGLĘDNY ZAKAZ DEDUKCJI: Nie zgaduj bazy porównawczej, nie łącz liczb z różnych akapitów na siłę "
            "i nie interpoluj trendu r/r, jeśli artykuł omawia wyłącznie bieżący miesiąc m/m.\n"
            "4. CZYSTOŚĆ DANYCH: W polu 'value' podawaj wyłącznie liczbę z jednostką (np. '5,80%', '906,4 tys.')."
        ),
    ),
    (
        "human",
        "Kraj: {country}\n\n"
        "WYNIKI WYSZUKIWANIA:\n{web_results}\n\n"
        "ZAUFANE DOMENY:\n{sources_context}\n\n"
        "Wyodrębnij wskaźniki gospodarcze z zachowaniem bezwzględnej dyscypliny faktograficznej.",
    ),
])


class EconomyDataFetcher:

  def __init__(self, agent_name: str = "GeminiAgent"):
    self.agent_name = agent_name
    self.llm = ChatGoogleGenerativeAI(
        model=config.DEFAULT_LLM_MODEL,
        google_api_key=config.GOOGLE_API_KEY,
        max_retries=1,
        timeout=30,
    )
    self.db = EconomyDatabase()

  def fetch_and_store_indicators(self, country: str, web_results: str):
    saved_sources = self.db.get_sources(country=country)
    sources_context = ""
    if saved_sources and saved_sources.sources:
      sources_context = "\n".join([f"- {s.name} ({s.url})" for s in saved_sources.sources])

    inputs = {
        "agent_name": self.agent_name,
        "country": country,
        "sources_context": sources_context,
        "web_results": web_results,
    }

    print(f"[{self.agent_name}] Ekstrakcja danych makroekonomicznych...")
    try:
      structured_llm = self.llm.with_structured_output(IndicatorResponse)
      chain = EXTRACTION_PROMPT | structured_llm
      result: IndicatorResponse = chain.invoke(inputs)
    except Exception as err:
      print(f"[{self.agent_name} Notice] Przełączanie awaryjne na model OpenAI: {err}")
      fallback_llm = ChatOpenAI(
          model=config.DEFAULT_OPENAI_MODEL,
          api_key=config.OPENAI_API_KEY,
          temperature=0.1,
      ).with_structured_output(IndicatorResponse)
      chain_fallback = EXTRACTION_PROMPT | fallback_llm
      result: IndicatorResponse = chain_fallback.invoke(inputs)

    self.db.save_indicators(
        agent_name=self.agent_name,
        country=result.country,
        indicators=result.indicators,
    )
    return result