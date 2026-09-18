import config
from langchain_openai import ChatOpenAI
from modules.data_fetcher import EXTRACTION_PROMPT, IndicatorResponse
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
    sources_context = ""
    if saved_sources and saved_sources.sources:
      sources_context = "\n".join([f"- {s.name} ({s.url})" for s in saved_sources.sources])

    structured_llm = self.llm.with_structured_output(IndicatorResponse)
    chain = EXTRACTION_PROMPT | structured_llm

    print(f"[{self.agent_name}] Ekstrakcja danych makroekonomicznych...")
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