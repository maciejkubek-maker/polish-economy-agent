import config
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from modules.data_fetcher import IndicatorResponse
from modules.database import EconomyDatabase


class OpenAIDataFetcher:

  def __init__(self, agent_name: str = "GPTAgent"):
    self.agent_name = agent_name
    self.llm = ChatOpenAI(
        model=config.DEFAULT_OPENAI_MODEL,
        api_key=config.OPENAI_API_KEY,
        temperature=0.1,
    )
    self.db = EconomyDatabase()

  def fetch_and_store_indicators(self, country: str, web_results: str):
    saved_sources = self.db.get_sources(country=country)
    if not saved_sources or not saved_sources.sources:
      raise ValueError(f"Brak zaufanych źródeł dla kraju {country} w bazie.")

    sources_context = "\n".join(
        [f"- {s.name} ({s.url}): {s.description}" for s in saved_sources.sources]
    )

    structured_llm = self.llm.with_structured_output(IndicatorResponse)

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "Jesteś zaawansowanym agentem ekonomicznym ({agent_name}). "
            "Twój cel to wyciągnięcie najbardziej aktualnych wskaźników makroekonomicznych "
            "dla wskazanego kraju na podstawie dostarczonych wyników wyszukiwania i źródeł referencyjnych.",
        ),
        (
            "human",
            "Kraj: {country}\n\n"
            "WYNIKI WYSZUKIWANIA SIECIOWEGO:\n{web_results}\n\n"
            "ZAUFANE ŹRÓDŁA ODNIESIENIA:\n{sources_context}\n\n"
            "Wyodrębnij i podaj najnowsze wskaźniki ekonomiczne.",
        ),
    ])

    chain = prompt | structured_llm

    print(f"[{self.agent_name}] Analiza i pobieranie wskaźników...")
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