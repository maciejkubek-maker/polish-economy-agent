from tavily import TavilyClient
import config


class WebSearchService:

  def __init__(self):
    self.client = TavilyClient(api_key=config.TAVILY_API_KEY)

  def search_indicators(self, country: str) -> str:
    # Zapytania oparte na oficjalnym nazewnictwie publikacji GUS/NBP bez sztywnego roku
    queries = [
        (
            f"GUS komunikat stopa bezrobocia rejestrowanego {country} rynek"
            " pracy liczba bezrobotnych dynamika r/r"
        ),
        (
            f"GUS szybki szacunek wskaźnik cen towarów i usług konsumpcyjnych"
            f" inflacja CPI {country} NBP stopy procentowe"
        ),
        (
            f"GUS dynamika produkcji sprzedanej przemysłu budowlano-montażowej"
            f" PKB dynamika r/r {country} koniunktura"
        ),
    ]

    all_snippets = []
    seen_urls = set()

    for query in queries:
      print(f"[Tavily Deep Search] Pobieranie: '{query[:60]}...'")
      try:
        # days=45 pobiera wyłącznie świeże publikacje z ostatniego półtora miesiąca
        response = self.client.search(
            query=query,
            search_depth="advanced",
            max_results=7,
            days=45,
            include_answer=False,
        )
        for res in response.get("results", []):
          url = res.get("url", "")
          if url not in seen_urls:
            seen_urls.add(url)
            all_snippets.append(
                f"ŹRÓDŁO: {res.get('title')}\nURL: {url}\nTREŚĆ"
                f" PUBLIKACJI:\n{res.get('content')}"
            )
      except Exception as err:
        print(f"[Tavily Warning] Błąd zapytania '{query}': {err}")

    print(
        f"[Tavily] Zebrano łącznie {len(all_snippets)} unikalnych analiz i"
        " komunikatów."
    )
    return "\n\n" + ("=" * 40) + "\n\n".join(all_snippets)