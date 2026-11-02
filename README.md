# Polish Economy Agent

> **Autonomiczny agent makroekonomiczny łączący oficjalne API instytucji publicznych (NBP, GUS, Eurostat), audytowalną platformę danych SQLite v2, wyszukiwanie kontekstowe Tavily oraz syntezę analityczną AI (Google Gemini / OpenAI GPT).**

Projekt demonstracyjny o charakterze **inżynieryjnego portfolio**, prezentujący produkcyjne podejście do automatycznego pozyskiwania, rygorystycznej walidacji, wersjonowania w modelu *append-only* oraz krytycznej analizy danych gospodarczych bez halucynacji i zgadywania.

---

## 1. Architektura Systemu

```text
       ┌────────────────────────────────────────────────────────┐
       │                OFICJALNE ŹRÓDŁA DANYCH                 │
       │   NBP (REST & XML) │ Eurostat (JSON-stat) │ GUS (BDL & DBW)│
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │        WARSTWA WALIDACJI I POBIERANIA (CONNECTORS)      │
       │  • Typy, jednostki, okresy, częstotliwości            │
       │  • Rejestracja dowodów surowych z hashem SHA-256       │
       │  • Obsługa częściowych awarii (PARTIAL run)            │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │             PLATFORMA DANYCH SQLITE V2                 │
       │  • observations (STRICTLY APPEND-ONLY via DB triggers) │
       │  • current_observations (deterministyczny widok stanu) │
       │  • source_evidence (pełna audytowalność pochodzenia)   │
       │  • quality_events (anomalie, braki mapowań)            │
       └──────────────┬──────────────────────────┬──────────────┘
                      │                          │
                      │                          ▼
                      │         ┌────────────────────────────────┐
                      │         │    TAVILY SEARCH ENRICHMENT    │
                      │         │  • OFFICIAL_COMMUNIQUE         │
                      │         │  • MEDIA_COMMENTARY            │
                      │         └────────────────┬───────────────┘
                      │                          │
                      ▼                          ▼
       ┌────────────────────────────────────────────────────────┐
       │               SYNTEZA ANALITYCZNA (AI EVALUATOR)        │
       │  • Model podstawowy: Google Gemini                     │
       │  • Model zapasowy: OpenAI GPT                          │
       │  • Tryb bezpłatny/demo: Deterministyczny silnik offline│
       │  • Wieloźródłowy aparat cytowań numerycznych [1], [2]  │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │                  RAPORT ANALITYCZNY                    │
       │  • 6 sekcji (trendy, ryzyka, Kowalski, biznes, werdykt)│
       │  • Publikacja HTML (Flask) i Markdown na dysku         │
       └────────────────────────────────────────────────────────┘
```

---

## 2. Jak Działają Oficjalne API i Konektory

Platforma korzysta z bezpłatnych, publicznych endpointów instytucji statystycznych i finansowych:

1. **Narodowy Bank Polski (NBP):**
   - **Kursy walutowe:** Oficjalne REST API (`https://api.nbp.pl/api/exchangerates/rates/A/{code}/`) — pobieranie średnich kursów EUR/PLN oraz USD/PLN z tabeli A.
   - **Stopa referencyjna:** Maszynowy plik XML publikowany przez NBP (`https://static.nbp.pl/dane/stopy/stopy_procentowe.xml`).
2. **Eurostat (European Commission):**
   - **Dissemination API 1.0 (format JSON-stat 2.0):**
     * **HICP (`teicp000`):** Zharmonizowany wskaźnik cen konsumpcyjnych r/r (COICOP 2018).
     * **Bezrobocie BAEL (`une_rt_m`):** Zharmonizowana stopa bezrobocia według metodologii ILO/Eurostat wyrównana sezonowo.
     * **Produkt Krajowy Brutto (`namq_10_gdp`):** Ścisłe metodologiczne rozdzielenie dynamiki kw/kw (`CLV_PCH_PRE`), dynamiki r/r (`CLV_PCH_SM`) oraz wolumenu w mln EUR (`CLV10_MEUR`).
3. **Główny Urząd Statystyczny (GUS):**
   - **Bank Danych Lokalnych (BDL API v1):** Stopa bezrobocia rejestrowanego (`var_id=60270`).
   - **Dziedzinowe Bazy Wiedzy (DBW API v1.1.0):** Wskaźnik cen towarów i usług konsumpcyjnych CPI r/r (`var_id=305`, `przekroj=736`, kody miesięcy 247–258).
4. **Tavily Search API:**
   - Wyszukiwanie bieżącego kontekstu gospodarczego z podziałem domen na oficjalne komunikaty (`stat.gov.pl`, `nbp.pl`) oraz analizy rynkowe i prasowe (`bankier.pl`, `businessinsider.com.pl`, `money.pl`).
5. **AI Evaluator (Gemini / GPT):**
   - Generowanie profesjonalnego, 6-sekcyjnego raportu makroekonomicznego z rygorystycznym aparatem cytowań `[X]`. W trybie offline stosowany jest deterministyczny silnik syntezy danych.

---

## 3. Jak Uruchomić Projekt

### Wymagania wstępne:
- Python w wersji **3.11** lub nowszej.
- Nowoczesny menedżer pakietów [`uv`](https://github.com/astral-sh/uv) (zalecany) lub standardowy `pip`.

### Klonowanie repozytorium i instalacja zależności:
```bash
git clone https://github.com/maciejkubek-maker/polish-economy-agent.git
cd polish-economy-agent

# Instalacja zależności przez uv
uv sync
```

---

### A. Tryb Demo / Offline (Bezpłatny, bez kluczy API)

Projekt jest w pełni przystosowany do demonstracji portfolio bez konieczności podawania jakichkolwiek płatnych kluczy API:

1. **Wygenerowanie raportu w trybie offline:**
   ```bash
   uv run python -c "import app; app.run_pipeline(use_v2=True, offline_mode=True)"
   ```
2. **Uruchomienie serwera aplikacji:**
   ```bash
   uv run python app.py
   ```
3. Otwórz przeglądarkę pod adresem: **`http://127.0.0.1:5000/`** lub przejrzyj wygenerowany plik `report.html`.

Tryb offline jest ustawieniem domyślnym. Powyższe polecenia nie wymagają kluczy API i nie wykonują wywołań do Tavily, Gemini ani OpenAI.

---

### B. Tryb Pełny (Live z pobieraniem z oficjalnych API i LLM)

Aby uruchomić pełne pobieranie z sieci i syntezę przez modele LLM:

1. Skonfiguruj plik `.env` w katalogu głównym projektu:
   ```env
   # Modele AI (skonfiguruj dostawców, których chcesz użyć w trybie live)
   GOOGLE_API_KEY=twoj_klucz_gemini_api
   OPENAI_API_KEY=twoj_klucz_openai_api

   # Wyszukiwanie wiadomości
   TAVILY_API_KEY=twoj_klucz_tavily_api

   # Tryb pracy (false = pobieranie live)
   OFFLINE_MODE=false
   DB_V2_PATH=instance/economy_agent_v2.db
   ```
2. Uruchom aplikację:
   ```bash
   uv run python app.py
   ```

---

### C. Uruchomienie Testów Automatycznych

Projekt posiada 129 kompleksowych testów jednostkowych i integracyjnych, działających w 100% offline w kilka sekund:

```bash
uv run pytest
```

---

## 4. Ograniczenia i Założenia Projektowe

Jako projekt inżynieryjny portfolio, aplikacja podlega świadomym regułom bezpieczeństwa i ograniczeniom domenowym:

1. **Zakaz zgadywania i halucynacji (No Guessing Policy):**
   - Jeśli oficjalne API zwraca błąd (np. 404 lub 503) bądź zmienna została wycofana ze słownika GUS (jak BDL 60269), system nie zmyśla liczb ani nie prosi modelu AI o „zgadnięcie”.
   - Wskaźnik otrzymuje status `Brak danych`, anomalia trafia do tabeli `quality_events`, a przebieg potoku oznacza się jako `PARTIAL`.
2. **Asynchroniczność wskaźników makroekonomicznych (Lagi publikacyjne):**
   - Dane makroekonomiczne spływają w różnych interwałach (PKB kwartalnie z opóźnieniem do 45 dni, bezrobocie i CPI miesięcznie z opóźnieniem 15–25 dni, kursy walut codziennie).
   - Raport transparentnie wskazuje horyzont czasowy poszczególnych odczytów w nagłówku i aparacie źródłowym.
3. **Bezwzględna nietykalność danych legacy:**
   - Pierwotna baza `instance/economy_agent.db` jest traktowana jako zablokowane archiwum (Read-Only) i nie ulega żadnym modyfikacjom. Nowe rekordy trafiają wyłącznie do schematu SQLite v2.
4. **Cel projektu:**
   - Narzędzie demonstruje architekturę autonomicznego agenta danych i audytowalnej platformy analitycznej. Nie stanowi ono oficjalnego serwisu statystyki publicznej ani doradztwa inwestycyjnego.

---

## 5. Licencja i Autorstwo

Projekt rozwijany przez [maciejkubek-maker](https://github.com/maciejkubek-maker) jako demonstrator architektury agentowej AI i inżynierii danych makroekonomicznych.
