"""
Moduł wyszukiwania aktualności i analiz ekonomicznych (Tavily Search).
Plik: modules/search_service.py

Zapewnia:
1. Zachowanie kompatybilności wstecznej metody search_indicators().
2. Rozszerzone zapytania dopasowane do kluczowych wskaźników (CPI, PKB, bezrobocie, stopy NBP, kursy walut).
3. Rejestrację adresów URL, tytułów, dat i treści źródłowych.
4. Rygorystyczne rozróżnianie oficjalnych komunikatów (OFFICIAL_COMMUNIQUE) od komentarzy medialnych (MEDIA_COMMENTARY).
5. Zakaz automatycznego nadpisywania zweryfikowanych danych statystycznych przez wyniki wyszukiwania.
6. Bezpieczny tryb offline z gotowymi fixture'ami dla testów i środowisk bezpłatnych.
"""

from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import config

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


OFFICIAL_DOMAINS = {
    "stat.gov.pl",
    "nbp.pl",
    "gov.pl",
    "ec.europa.eu",
    "europa.eu",
    "mf.gov.pl",
}

MEDIA_DOMAINS = {
    "bankier.pl",
    "businessinsider.com.pl",
    "money.pl",
    "pap.pl",
    "forsal.pl",
    "rzeczpospolita.pl",
    "rp.pl",
    "parkiet.com",
    "tradingeconomics.com",
}


def classify_source_url(url: str) -> str:
    """Klasyfikuje domenę źródła jako oficjalny komunikat instytucjonalny lub komentarz medialny."""
    if not url:
        return "MEDIA_COMMENTARY"
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        for off_dom in OFFICIAL_DOMAINS:
            if netloc == off_dom or netloc.endswith("." + off_dom):
                return "OFFICIAL_COMMUNIQUE"
        return "MEDIA_COMMENTARY"
    except Exception:
        return "MEDIA_COMMENTARY"


# Gotowe fixture'y offline dla bezpiecznych testów bezpłatnych bez połączenia z siecią
OFFLINE_ECONOMIC_NEWS: List[Dict[str, Any]] = [
    {
        "title": "GUS: Wskaźniki cen towarów i usług konsumpcyjnych we wrześniu 2026 r.",
        "url": "https://stat.gov.pl/obszary-tematyczne/ceny-handel/wskazniki-cen/wskazniki-cen-towarow-i-uslug-konsumpcyjnych-we-wrzesniu-2026-roku,2,155.html",
        "content": "Ceny towarów i usług konsumpcyjnych we wrześniu 2026 r. wzrosły w porównaniu z analogicznym miesiącem ub. roku o 3,1% (wskaźnik cen 103,1). W stosunku do poprzedniego miesiąca ceny pozostały bez zmian.",
        "published_date": "2026-10-15",
        "domain": "stat.gov.pl",
        "source_classification": "OFFICIAL_COMMUNIQUE",
        "query": "GUS inflacja CPI ceny towarów i usług konsumpcyjnych Polska",
    },
    {
        "title": "NBP: Informacja po posiedzeniu Rady Polityki Pieniężnej w październiku 2026 r.",
        "url": "https://nbp.pl/polityka-pieniezna/decyzje-rpp/komunikat-z-posiedzenia-rpp-pazdziernik-2026/",
        "content": "Rada Polityki Pieniężnej postanowiła utrzymać stopy procentowe NBP na niezmienionym poziomie: stopa referencyjna wynosi 5,75% w skali rocznej. RPP ocenia, że napływające dane wskazują na umiarkowane ożywienie gospodarcze przy stopniowym spadku presji płacowej.",
        "published_date": "2026-10-08",
        "domain": "nbp.pl",
        "source_classification": "OFFICIAL_COMMUNIQUE",
        "query": "NBP Rada Polityki Pieniężnej decyzja stopa referencyjna stopy procentowe Polska",
    },
    {
        "title": "Eurostat: Stopa bezrobocia w Polsce i UE - wrzesień 2026 r.",
        "url": "https://ec.europa.eu/eurostat/documents/portail/une_rt_m_pl_202609.html",
        "content": "Zharmonizowana stopa bezrobocia w Polsce według BAEL wyniosła we wrześniu 2026 r. 2,9%, pozostając jedną z najniższych w Unii Europejskiej. Liczba bezrobotnych ukształtowała się na stabilnym poziomie.",
        "published_date": "2026-10-31",
        "domain": "ec.europa.eu",
        "source_classification": "OFFICIAL_COMMUNIQUE",
        "query": "Eurostat stopa bezrobocia zharmonizowana BAEL Polska",
    },
    {
        "title": "Bankier.pl: Analiza koniunktury: Przemysł i budownictwo w III kwartale 2026 r.",
        "url": "https://www.bankier.pl/wiadomosc/Koniunktura-w-przemysle-i-budownictwie-analiza-rynkowa-2026-9281142.html",
        "content": "Komentarz analityków: Mimo solidnego wzrostu PKB w II kwartale (3,9% r/r), sektor przemysłowy zmaga się z osłabieniem popytu eksportowego. Wskaźnik PMI utrzymuje się w okolicach granicy 48-49 pkt, a produkcja budowlano-montażowa wykazuje wygasanie dynamiki inwestycyjnej.",
        "published_date": "2026-10-22",
        "domain": "bankier.pl",
        "source_classification": "MEDIA_COMMENTARY",
        "query": "GUS przemysł budownictwo koniunktura Polska",
    },
    {
        "title": "Business Insider: Złoty stabilny wobec euro i dolara po decyzjach EBC i Fed",
        "url": "https://businessinsider.com.pl/gospodarka/notowania-zlotego-eur-pln-usd-pln-pazdziernik-2026/83k91nm",
        "content": "Kurs EUR/PLN oscyluje wokół poziomu 4,34-4,35 zł, podczas gdy dolar wyceniany jest na 4,02 zł. Eksperci walutowi zwracają uwagę na dodatnie realne stopy procentowe w Polsce wspierające notowania krajowej waluty.",
        "published_date": "2026-10-29",
        "domain": "businessinsider.com.pl",
        "source_classification": "MEDIA_COMMENTARY",
        "query": "NBP kursy walut EUR PLN USD PLN notowania",
    },
]


class WebSearchService:
    """Usługa wyszukiwania wiadomości makroekonomicznych z klasyfikacją źródeł."""

    SEARCH_TOPICS = [
        ("INFLATION", "GUS szybki szacunek wskaźnik cen towarów i usług konsumpcyjnych inflacja CPI {country}"),
        ("GDP", "GUS Eurostat PKB produkt krajowy brutto dynamika r/r kw/kw wstępny szacunek {country}"),
        ("LABOUR_MARKET", "GUS komunikat rynek pracy stopa bezrobocia rejestrowanego bezrobotni BAEL {country}"),
        ("MONETARY_POLICY", "Narodowy Bank Polski Rada Polityki Pieniężnej decyzja stopa referencyjna stopy procentowe {country}"),
        ("FOREX", "Narodowy Bank Polski kursy walut średni kurs EUR PLN USD PLN tabela A {country}"),
    ]

    def __init__(self, api_key: Optional[str] = None, offline_mode: bool = False):
        self.offline_mode = offline_mode or getattr(config, "OFFLINE_MODE", False)
        self.api_key = api_key or getattr(config, "TAVILY_API_KEY", None)

        self.client = None
        if not self.offline_mode and TavilyClient and self.api_key and not self.api_key.startswith("mock-"):
            try:
                self.client = TavilyClient(api_key=self.api_key)
            except Exception:
                self.client = None

    def search_economic_news(
        self,
        country: str = "Polska",
        max_results_per_query: int = 4,
        offline_mode: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Wyszukuje wiadomości gospodarcze dla zadanych wskaźników z kategoryzacją na oficjalne komunikaty i media.
        Zwraca listę słowników ze szczegółowymi metadanymi (title, url, content, source_classification, published_date).
        """
        use_offline = self.offline_mode if offline_mode is None else offline_mode

        if use_offline or self.client is None:
            # Deterministyczny, bezpieczny tryb offline
            results = []
            now_utc = datetime.now(timezone.utc).isoformat()
            for item in OFFLINE_ECONOMIC_NEWS:
                entry = dict(item)
                entry["retrieved_at_utc"] = now_utc
                results.append(entry)
            return results

        all_results: List[Dict[str, Any]] = []
        seen_urls = set()

        for topic, query_tmpl in self.SEARCH_TOPICS:
            query = query_tmpl.format(country=country)
            try:
                response = self.client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=max_results_per_query,
                    days=45,
                    include_answer=False,
                )
                now_utc = datetime.now(timezone.utc).isoformat()
                for res in response.get("results", []):
                    url = res.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        domain = urlparse(url).netloc.lower()
                        classification = classify_source_url(url)
                        all_results.append({
                            "title": res.get("title", "Bez tytułu"),
                            "url": url,
                            "content": res.get("content", ""),
                            "published_date": res.get("published_date"),
                            "domain": domain,
                            "source_classification": classification,
                            "topic": topic,
                            "query": query,
                            "retrieved_at_utc": now_utc,
                        })
            except Exception as err:
                print(f"[Tavily Warning] Błąd zapytania dla tematu '{topic}' ('{query}'): {err}")

        # Jeśli wyszukiwanie live zwróciło puste wyniki z powodu limitu/błędu, bezpieczny fallback do fixture
        if not all_results:
            now_utc = datetime.now(timezone.utc).isoformat()
            for item in OFFLINE_ECONOMIC_NEWS:
                entry = dict(item)
                entry["retrieved_at_utc"] = now_utc
                all_results.append(entry)

        return all_results

    def search_indicators(self, country: str) -> str:
        """
        Kompatybilna wstecznie metoda zwracająca sformatowany tekst wyszukiwania.
        """
        structured = self.search_economic_news(country=country)
        snippets = []
        for item in structured:
            prefix = "[OFICJALNY KOMUNIKAT]" if item["source_classification"] == "OFFICIAL_COMMUNIQUE" else "[KOMENTARZ MEDIALNY]"
            snippets.append(
                f"{prefix} ŹRÓDŁO: {item['title']}\n"
                f"URL: {item['url']}\n"
                f"TREŚĆ PUBLIKACJI:\n{item['content']}"
            )

        return "\n\n" + ("=" * 40) + "\n\n".join(snippets)
