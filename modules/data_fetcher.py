import config
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from modules.database import EconomyDatabase
from modules.search_service import WebSearchService
from pydantic import BaseModel, Field
from typing import List


class IndicatorItem(BaseModel):
  indicator_name: str = Field(
      description="Nazwa wskaźnika (np. PKB, Inflacja CPI, Stopa bezrobocia)"
  )
  value: str = Field(
      description="Aktualna wartość wskaźnika wraz z jednostką (np. 2.5%, 5.1%)"
  )
  period: str = Field(description="Okres, którego dotyczy (np. Q1 2026, Rok 2025)")
  source_name: str = Field(
      description="Nazwa zaufanego źródła, z którego pozyskano informację"
  )
  page_info: str = Field(
      description="Szczegółowa informacja lub kontekst pozyskany ze źródła oraz URL"
  )


class IndicatorResponse(BaseModel):
  country: str
  indicators: List[IndicatorItem]


class EconomyDataFetcher:

  def __init__(self, agent_name: str = "GeminiAgent"):
    self.agent_name = agent_name
    self.llm = ChatGoogleGenerativeAI(
        model=config.DEFAULT_LLM_MODEL, google_api_key=config.GOOGLE_API_KEY
    )
    self.db = EconomyDatabase()
    self.search_service = WebSearchService()

  def fetch_and_store_indicators(self, country: str):
    saved_sources = self.db.get_sources(country=country)
    if not saved_sources or not saved_sources.sources:
      raise ValueError(f"Brak zaufanych źródeł dla kraju {country} w bazie.")

    sources_context = "\n".join(
        [f"- {s.name} ({s.url}): {s.description}" for s in saved_sources.sources]
    )

    # Realne wyniki z wyszukiwarki Tavily
    web_results = self.search_service.search_indicators(country=country)

    parser = PydanticOutputParser(pydantic_object=IndicatorResponse)

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            (
                "Jesteś zaawansowanym agentem ekonomicznym ({agent_name})."
                " Twój cel to wyciągnięcie najbardziej aktualnych wskaźników"
                " makroekonomicznych.\n\n"
                "KORZYSTAJ PRZEDE WSZYSTKIM Z BIEŻĄCYCH WYNIKÓW WYSZUKIWANIA"
                " SIECIOWEGO:\n{web_results}\n\n"
                "Zaufane źródła odniesienia:\n{sources_context}\n\n"
                "{format_instructions}"
            ),
        ),
        (
            "human",
            "Pobierz najnowsze wskaźniki ekonomiczne dla kraju: {country}",
        ),
    ])

    chain = prompt | self.llm | parser

    print(f"[{self.agent_name}] Analiza i pobieranie wskaźników...")
    result = chain.invoke({
        "agent_name": self.agent_name,
        "country": country,
        "sources_context": sources_context,
        "web_results": web_results,
        "format_instructions": parser.get_format_instructions(),
    })

    self.db.save_indicators(
        agent_name=self.agent_name,
        country=result.country,
        indicators=result.indicators,
    )
    return result