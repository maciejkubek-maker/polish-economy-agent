import datetime
from tavily import TavilyClient
import config


class WebSearchService:

  def __init__(self):
    self.client = TavilyClient(api_key=config.TAVILY_API_KEY)

  def search_indicators(self, country: str) -> str:
    current_year = datetime.datetime.now().year
    query = (
        f"Najnowsze wskaźniki makroekonomiczne {country} PKB inflacja CPI stopa"
        f" bezrobocia stopy procentowe GUS NBP {current_year}"
    )

    print(f"[Tavily Search] Przeszukiwanie sieci dla zapytania: '{query}'...")
    response = self.client.search(
        query=query, search_depth="advanced", max_results=5
    )

    snippets = []
    for result in response.get("results", []):
      snippets.append(
          f"Tytuł: {result['title']}\nURL: {result['url']}\nTreść:"
          f" {result['content']}"
      )

    return "\n\n---\n\n".join(snippets)