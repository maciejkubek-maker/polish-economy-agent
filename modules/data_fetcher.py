from typing import List
import config
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from modules.database import EconomyDatabase
from pydantic import BaseModel, Field


class IndicatorItem(BaseModel):
  indicator_name: str = Field(
      description="Nazwa wskaźnika (np. PKB r/r, Inflacja CPI, Stopa bezrobocia)"
  )
  value: str = Field(
      description="Wartość wskaźnika wraz z jednostką (np. 3.90%, 5.80%)"
  )
  period: str = Field(description="Okres wskaźnika (np. II kw. 2026, VII 2026)")
  source_name: str = Field(
      description="Oficjalna nazwa instytucji lub serwisu źródłowego"
  )
  page_info: str = Field(
      description="Kontekst oraz pełny adres URL strony ze źródłem"
  )


class IndicatorResponse(BaseModel):
  country: str
  indicators: List[IndicatorItem]


class EconomyDataFetcher:

  def __init__(self, agent_name: str = "GeminiAgent"):
    self.agent_name = agent_name
    self.llm = ChatGoogleGenerativeAI(
        model=config.DEFAULT_LLM_MODEL,
        google_api_key=config.GOOGLE_API_KEY,
    )
    self.db = EconomyDatabase()

  def fetch_and_store_indicators(self, country: str, web_results: str):
    saved_sources = self.db.get_sources(country=country)
    sources_context = ""
    if saved_sources and saved_sources.sources:
      sources_context = "\n".join(
          [f"- {s.name} ({s.url})" for s in saved_sources.sources]
      )

    structured_llm = self.llm.with_structured_output(IndicatorResponse)

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            (
                "Jesteś agentem analitycznym ({agent_name}). Wyodrębnij z"
                " wyników wyszukiwania twarde dane makroekonomiczne dla"
                " wskazanego kraju. Zwracaj dokładne wskaźniki, ich okresy,"
                " instytucje źródłowe oraz adresy URL."
            ),
        ),
        (
            "human",
            "Kraj: {country}\n\n"
            "WYNIKI WYSZUKIWANIA:\n{web_results}\n\n"
            "ZAUFANE ŹRÓDŁA:\n{sources_context}\n\n"
            "Wyodrębnij kluczowe wskaźniki makroekonomiczne.",
        ),
    ])

    chain = prompt | structured_llm
    print(f"[{self.agent_name}] Analiza wskaźników...")
    result: IndicatorResponse = chain.invoke({
        "agent_name": self.agent_name,
        "country": country,
        "sources_context": sources_context,
        "web_results": web_results,
    })

    self.db.save_indicators(
        agent_name=self.agent_name,
        country=result.country,
        indicators=result.indicators,
    )
    return result