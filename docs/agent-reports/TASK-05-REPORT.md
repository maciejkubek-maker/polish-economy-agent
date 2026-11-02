# Raport z Realizacji TASK-05 — Oficjalne Konektory API (NBP, Eurostat, GUS)

**Data wykonania:** 2026-11-02  
**Autor:** Antigravity (DeepMind Agent)  
**Gałąź robocza:** `feature/data-platform-v2`  
**Baza docelowa PR:** PR #4 (`feature/data-platform-v2` -> `main`)  
**Status zadania:** `COMPLETED`  

---

## 1. Cel i Zakres Prac

Zgodnie z poleceniem i standardem `AGENTS.md` (w tym zasadą 8 i 12 dotyczącą zakazu halucynacji i fikcyjnych identyfikatorów), zaimplementowano produkcyjny pakiet konektorów do oficjalnych instytucjonalnych interfejsów programistycznych:
1. **Narodowy Bank Polski (NBP):**
   - Średnie kursy walut EUR/PLN oraz USD/PLN z oficjalnego REST API (`https://api.nbp.pl/api/exchangerates/rates/A/{code}/?format=json`).
   - Stopa referencyjna NBP z oficjalnego pliku maszynowego XML (`https://static.nbp.pl/dane/stopy/stopy_procentowe.xml`).
2. **Eurostat (Statistics API 1.0 — JSON-stat 2.0):**
   - HICP — Zharmonizowany Wskaźnik Cen Konsumpcyjnych (`prc_hicp_manr`).
   - Stopa bezrobocia zharmonizowanego wg BAEL/ILO (`une_rt_m`).
   - Kwartalny wolumen / wzrost realnego PKB (`namq_10_gdp`).
3. **Główny Urząd Statystyczny (GUS):**
   - Stopa bezrobocia rejestrowanego (`PL_UNEMPLOYMENT_REGISTERED_RATE`) — zweryfikowane API BDL (`var_id=60270`).
   - Liczba bezrobotnych zarejestrowanych (`PL_UNEMPLOYMENT_REGISTERED_COUNT`) — zweryfikowane API BDL (`var_id=60269`).
   - Wskaźnik cen towarów i usług konsumpcyjnych CPI r/r (`PL_CPI_YOY`) — zweryfikowane API DBW (`id-zmienna=305`, `id-przekroj=736`).
   - Dynamiczne wyszukiwanie zmiennych (`search_bdl_variables`) w celu bezpiecznego odkrywania bez ryzyka przestarzałych ID.
   - **Rygorystyczny zakaz fikcyjnych ID:** Wskaźniki wymagające zmapowania (`PL_WAGE_AVERAGE_GROSS`, `PL_INDUSTRIAL_PRODUCTION_YOY`, `PL_GDP_YOY`) podnoszą dedykowany wyjątek `VariableNotMappedError` przy próbie wywołania bez zweryfikowanego identyfikatora.

---

## 2. Architektura i Zaimplementowane Moduły

Struktura pakietu `modules/connectors/`:
```
modules/connectors/
├── __init__.py         # Eksport publicznego API konektorów i modeli
├── base.py             # Klasa bazowa BaseConnector, RawEvidence, MacroObservation, walidatory, retry/timeout
├── nbp.py              # NbpConnector (REST + XML stóp)
├── eurostat.py         # EurostatConnector (JSON-stat 2.0 parser, daty miesięczne i kwartalne)
└── gus.py              # GusConnector (BDL, DBW, dynamic search, rygor braku fikcyjnych ID)
```

### Kluczowe mechanizmy bezpieczeństwa i jakości:
- **`RawEvidence` i `MacroObservation`:** Każde zapytanie rejestruje surową odpowiedź (RAW) z unikalnym `evidence_id`, stemplem UTC, statusem HTTP oraz deterministycznym hashem **SHA-256** treści. Obserwacja (VALIDATED) zachowuje pełen ślad pochodzenia (`evidence_id`).
- **Determinizm i walidacja typów:** Wartości liczbowe konwertowane są do kanonicznego typu `Decimal` z kontrolą dopuszczalnych zakresów dziedzinowych (np. kursy walut 0.5–20.0 PLN, stopa referencyjna 0–100%).
- **Ścisłe formaty ISO:** Walidacja dat do `YYYY-MM-DD`, normalizacja kodów jednostek (`PCT`, `EUR_PLN`, `USD_PLN`, `THOUSAND_PERSONS`, itp.) oraz częstotliwości (`DAILY`, `MONTHLY`, `QUARTERLY`, `ANNUAL`, `IRREGULAR`).
- **Odporność sieciowa:** Wbudowana obsługa retry (wykładniczy backoff), konfigurowalny timeout, natychmiastowe rzucanie `DataNotFoundError` przy braku danych (kod 404 lub pusta seria) bez prób zgadywania.
- **Tryb Offline (Offline Fixture Registration):** Wszystkie konektory posiadają wbudowany rejestr `register_fixture(keyword, payload, code)`, który w połączeniu z `offline_mode=True` uniemożliwia wykonanie jakichkolwiek nieautoryzowanych połączeń sieciowych w testach.

---

## 3. Rola Tavily Web Search, Gemini i GPT (Architektura Równoległa)

Wdrożenie oficjalnych konektorów API nie zastępuje, lecz ściśle uzupełnia wieloagentową architekturę dwukanałową (ADR-001) i weryfikację dwumodelową (ADR-002):
1. **Oficjalne API (NBP, Eurostat, GUS):** Dostarczają twarde, zweryfikowane serie liczbowe, rewizje i metadane bezpośrednio do warstwy `source_evidence` i `observations` bazy SQLite v2.
2. **Tavily Web Search:** Odpowiada za:
   - Szybkie szacunki (Flash estimates) publikowane przez GUS w formie komunikatów prasowych (zanim trafią do baz DBW/BDL).
   - Wskaźniki bez darmowego API REST (PMI dla przemysłu S&P Global, inflacja bazowa NBP).
   - Bieżący kontekst makroekonomiczny (czynniki jednorazowe, tarcze, decyzje rządu).
3. **Gemini & GPT:**
   - **Gemini:** Strukturalna synteza raportów na podstawie zweryfikowanych obserwacji, ekstrakcja tabel z komunikatów flash, wyliczanie horyzontu wykonawczego.
   - **GPT:** Druga niezależna opinia analityczna, weryfikacja krzyżowa wniosków i audyt spójności logicznej z danymi bazowymi.
   - Modele operują wyłącznie na obserwacjach ze statusem `VERIFIED` lub jawnie oznaczonych jako `PENDING`/`CONFLICT`.

---

## 4. Wyniki Testów i Weryfikacja Nienaruszalności

### A. Testy Konektorów (`tests/test_connectors.py`):
Utworzono 22 testy jednostkowe i integracyjne, w 100% działające w trybie offline:
- `TestNbpConnector`: kurs EUR, kurs USD, XML stóp procentowych, walidacja walut, obsługa 404/pustych serii, walidacja XML.
- `TestEurostatConnector`: parsowanie JSON-stat 2.0 dla HICP, bezrobocia BAEL, PKB kwartalnego, walidacja brakujących wymiarów.
- `TestGusConnector`: pobieranie stopy bezrobocia BDL (60270), liczby bezrobotnych BDL (60269), CPI DBW (305/736) z przeliczeniem indeksu bazowego 100, wyszukiwanie zmiennych, rygorystyczny test zakazu fikcyjnych ID (`VariableNotMappedError`), pobieranie ze zweryfikowanym ID.
- `TestBaseConnectorGuards`: blokada wywołań sieciowych w trybie offline, walidacja przecinków i spacji w liczbach, zakresy dopuszczalne, formaty ISO, jednostki i częstotliwości, unikalność ID i hash SHA-256 dowodu.

**Wynik:**
```
tests/test_connectors.py: 22 passed in 0.07s (100% green)
```

### B. Pełny Zestaw Testów Repozytorium:
```
============================= 98 passed in 6.18s ==============================
```
Wszystkie 98 testów (konektory, migrator v2, bezpieczeństwo HTML, izolacja SQLite, schemat v2, horyzont wykonawczy) przeszło pomyślnie.

### C. Nienaruszalność Bazy Legacy:
- Ścieżka: `instance/economy_agent.db`
- Rozmiar: dokładnie **73 728 bajtów**
- Suma SHA-256: `E6C5F318FFE1ECEEB34191A7A74EC9F7F7DE6069C4F298850792734277ECDE3B` (identyczna ze stanem bazowym).

---

## 5. Status Commitów i Git

- **Branch:** `feature/data-platform-v2`
- **Draft PR:** [PR #4](https://github.com/maciejkubek-maker/polish-economy-agent/pull/4)
- **Commit TASK-04:** `ac4f7f821a1caa1756d50c114044bb30c3664197`
- **Commit TASK-05:** `f3f7ce8a12ffd138902338b22910fc4c11854ca7`
