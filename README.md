# Polish Economy Agent

[English](#english) · [Polski](#polski)

<a id="english"></a>

## English

### Overview

Polish Economy Agent is an engineering portfolio project that demonstrates an auditable pipeline for collecting, validating, storing, and presenting selected macroeconomic indicators for Poland. It combines official public-data APIs with web-search context and can generate a cited analytical report either through supported language models or through a deterministic offline generator.

The project is a local prototype, not a deployed production service, an official statistical publication, or financial advice.

### What it does

- collects selected exchange-rate, interest-rate, inflation, labour-market, and GDP observations from NBP, GUS, and Eurostat connectors;
- validates source payloads, indicator definitions, units, periods, and frequencies before persistence;
- stores observations in an auditable SQLite v2 schema with source evidence, quality events, versioning, and append-only protection;
- enriches the factual dataset with Tavily search results classified as official communications or media commentary;
- keeps registered unemployment, LFS/BAEL unemployment, CPI variants, and GDP growth definitions separate;
- generates a six-section report with numbered citations and explicit `Brak danych` / `No data` handling instead of invented values;
- renders escaped and sanitised HTML and serves the latest report through Flask;
- supports partial connector failures without silently replacing missing observations.

### Data flow

```mermaid
flowchart LR
    Official["Official APIs<br/>NBP · GUS · Eurostat"] --> Connectors["Source connectors"]
    Connectors --> Validation["Validation<br/>definitions · units · periods"]
    Validation --> SQLite["SQLite v2<br/>evidence · observations · quality events"]

    Tavily["Tavily Search"] --> Context["Context<br/>official communications · media commentary"]

    SQLite --> Mode{"Report generation mode"}
    Context --> Mode
    Mode -->|Online| AI["AI analysis<br/>LangChain · Gemini or OpenAI GPT"]
    Mode -->|Offline| Offline["Deterministic offline generator"]
    AI --> HTML["Sanitised HTML report<br/>citations · sources · missing-data labels"]
    Offline --> HTML
    HTML --> Flask["Flask<br/>/ and /report.html"]
```

The official-data and Tavily paths are complementary. Numerical observations originate from the connector and validation path; search results provide separately labelled context and source evidence.

### Technology stack

| Technology | Role in the project |
|---|---|
| Python 3.11+ | Application, connectors, validation, orchestration, and reporting |
| Flask | Local HTML report server |
| SQLite v2 | Auditable persistence for runs, evidence, observations, quality events, and reports |
| NBP API | EUR/PLN and USD/PLN rates and the NBP reference rate |
| GUS API | Selected BDL and DBW indicators, including registered unemployment and CPI |
| Eurostat API | HICP, LFS/BAEL unemployment, and GDP series |
| Tavily | Optional online search context and source snippets |
| LangChain | Prompt, model, parser, and callback integration |
| Google Gemini | Primary optional online report model |
| OpenAI GPT | Optional fallback online report model |
| pytest | Offline unit, security, connector, storage, migration, and pipeline tests |
| uv | Reproducible dependency and test runner workflow |

### Quick start: offline demo

The default mode is offline. It requires no API keys and does not call NBP, GUS, Eurostat, Tavily, Gemini, or OpenAI. The pipeline uses deterministic local fixtures, writes only to the SQLite v2 database, generates `report.html`, and starts Flask locally.

> **Data notice:** offline fixture values are illustrative demonstration data. They are not live, current, or suitable for economic decisions.

Requirements: Python 3.11 or newer and `uv`.

```bash
git clone --branch feature/data-platform-v2 https://github.com/maciejkubek-maker/polish-economy-agent.git
cd polish-economy-agent
uv sync --group dev
uv run python app.py
```

Open <http://127.0.0.1:5000/> or <http://127.0.0.1:5000/report.html>. Stop the local server with `Ctrl+C`.

No `.env` file is needed for this mode. Do not set `DB_V2_PATH` to `instance/economy_agent.db`; that legacy database is protected and must remain unchanged.

### Optional online mode

Online mode contacts external services and may create billable model or search requests depending on the configured accounts. Enable it only when you intend to use those services.

Create a local `.env` file that is not committed:

```dotenv
OFFLINE_MODE=false
DB_V2_PATH=instance/economy_agent_v2.db

GOOGLE_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key
TAVILY_API_KEY=your_tavily_key
```

Then run:

```bash
uv run python app.py
```

In online report generation, the evaluator tries Gemini first, then OpenAI GPT, and falls back to deterministic synthesis if both are unavailable. Live official-data calls and live Tavily context also require network access; Tavily uses its local demo fixtures when no usable client is configured.

### Tests

The final TASK-06 audit passed **130 tests** offline:

```bash
uv sync --group dev
uv run pytest -q
```

Expected audited result: `130 passed`.

<a id="report-screenshots"></a>

### Report screenshots

> **Screenshot placeholder 1:** full HTML report overview.

> **Screenshot placeholder 2:** source citations and evidence section.

No image links are included until the screenshots are added to the repository.

### Scope and limitations

- Coverage is intentionally limited to the indicators implemented by the current connectors.
- Release schedules differ, so one report can contain daily, monthly, quarterly, and annual periods.
- Search snippets are untrusted context, not authoritative numerical observations or instructions for the agent.
- LLM output is not treated as source data; reports are built from stored observations and evidence.
- The repository is a portfolio prototype and has no production deployment, scheduler, public API, dashboard, or interactive charts.
- See the [documentation index](docs/INDEX.md) for architecture, data-contract, migration, quality, and source-policy notes.

---

<a id="polski"></a>

## Polski

### O projekcie

Polish Economy Agent to projekt portfolio inżynierskiego prezentujący audytowalny potok pozyskiwania, walidacji, zapisu i prezentacji wybranych wskaźników makroekonomicznych dla Polski. Łączy oficjalne API danych publicznych z kontekstem wyszukiwania internetowego i generuje raport analityczny z przypisami za pomocą obsługiwanych modeli językowych albo deterministycznego generatora offline.

Projekt jest lokalnym prototypem. Nie jest wdrożonym systemem produkcyjnym, oficjalną publikacją statystyczną ani poradą finansową.

### Funkcjonalności

- pobieranie wybranych kursów walut, stóp procentowych, danych o inflacji, rynku pracy i PKB przez konektory NBP, GUS i Eurostatu;
- walidacja odpowiedzi źródłowych, definicji wskaźników, jednostek, okresów i częstotliwości przed zapisem;
- audytowalny zapis w SQLite v2 z dowodami źródłowymi, zdarzeniami jakościowymi, wersjonowaniem i ochroną append-only;
- wzbogacanie danych o wyniki Tavily sklasyfikowane jako komunikaty oficjalne lub komentarze medialne;
- rozdzielenie m.in. bezrobocia rejestrowanego od BAEL, wariantów CPI oraz dynamiki PKB kw/kw od r/r;
- sześciosekcyjny raport z numerowanymi przypisami i jawnym oznaczeniem `Brak danych` zamiast zgadywania wartości;
- bezpieczne renderowanie HTML z escapowaniem i sanityzacją oraz udostępnianie raportu przez Flask;
- kontrolowana obsługa częściowych awarii konektorów.

### Przepływ danych

```mermaid
flowchart LR
    Official["Oficjalne API<br/>NBP · GUS · Eurostat"] --> Connectors["Konektory źródłowe"]
    Connectors --> Validation["Walidacja<br/>definicje · jednostki · okresy"]
    Validation --> SQLite["SQLite v2<br/>dowody · obserwacje · zdarzenia jakościowe"]

    Tavily["Tavily Search"] --> Context["Kontekst<br/>komunikaty oficjalne · komentarze medialne"]

    SQLite --> Mode{"Tryb generowania raportu"}
    Context --> Mode
    Mode -->|Online| AI["Analiza AI<br/>LangChain · Gemini lub OpenAI GPT"]
    Mode -->|Offline| Offline["Deterministyczny generator offline"]
    AI --> HTML["Sanityzowany raport HTML<br/>przypisy · źródła · oznaczenia braków"]
    Offline --> HTML
    HTML --> Flask["Flask<br/>/ i /report.html"]
```

Ścieżki danych oficjalnych i Tavily wzajemnie się uzupełniają. Obserwacje liczbowe pochodzą z konektorów i walidacji, natomiast wyniki wyszukiwania dostarczają oddzielnie oznaczony kontekst i dowody źródłowe.

### Technologie

| Technologia | Rola w projekcie |
|---|---|
| Python 3.11+ | Aplikacja, konektory, walidacja, orkiestracja i raportowanie |
| Flask | Lokalny serwer raportu HTML |
| SQLite v2 | Audytowalny zapis przebiegów, dowodów, obserwacji, zdarzeń jakościowych i raportów |
| NBP API | Kursy EUR/PLN i USD/PLN oraz stopa referencyjna NBP |
| GUS API | Wybrane wskaźniki BDL i DBW, w tym bezrobocie rejestrowane i CPI |
| Eurostat API | HICP, bezrobocie BAEL i szeregi PKB |
| Tavily | Opcjonalny kontekst wyszukiwania online i wycinki źródłowe |
| LangChain | Integracja promptów, modeli, parserów i callbacków |
| Google Gemini | Podstawowy opcjonalny model raportowania online |
| OpenAI GPT | Opcjonalny zapasowy model raportowania online |
| pytest | Testy offline: jednostkowe, bezpieczeństwa, konektorów, bazy, migracji i potoku |
| uv | Powtarzalna instalacja zależności i uruchamianie testów |

### Szybki start: demo offline

Tryb offline jest domyślny. Nie wymaga kluczy API i nie łączy się z NBP, GUS, Eurostatem, Tavily, Gemini ani OpenAI. Potok korzysta z deterministycznych lokalnych fixture'ów, zapisuje dane wyłącznie w bazie SQLite v2, generuje `report.html` i uruchamia lokalny serwer Flask.

> **Informacja o danych:** wartości we fixture'ach offline są przykładowymi danymi demonstracyjnymi. Nie są danymi bieżącymi ani podstawą do decyzji ekonomicznych.

Wymagania: Python 3.11 lub nowszy oraz `uv`.

```bash
git clone --branch feature/data-platform-v2 https://github.com/maciejkubek-maker/polish-economy-agent.git
cd polish-economy-agent
uv sync --group dev
uv run python app.py
```

Otwórz <http://127.0.0.1:5000/> lub <http://127.0.0.1:5000/report.html>. Zatrzymaj lokalny serwer skrótem `Ctrl+C`.

W tym trybie plik `.env` nie jest potrzebny. Nie ustawiaj `DB_V2_PATH` na `instance/economy_agent.db`; ta baza legacy jest chroniona i musi pozostać niezmieniona.

### Opcjonalny tryb online

Tryb online łączy się z usługami zewnętrznymi i zależnie od skonfigurowanych kont może powodować płatne wywołania modeli lub wyszukiwarki. Włączaj go wyłącznie świadomie.

Utwórz lokalny, niecommitowany plik `.env`:

```dotenv
OFFLINE_MODE=false
DB_V2_PATH=instance/economy_agent_v2.db

GOOGLE_API_KEY=twoj_klucz_gemini
OPENAI_API_KEY=twoj_klucz_openai
TAVILY_API_KEY=twoj_klucz_tavily
```

Następnie uruchom:

```bash
uv run python app.py
```

Podczas generowania online evaluator najpierw próbuje Gemini, następnie OpenAI GPT, a przy braku obu modeli przechodzi do syntezy deterministycznej. Pobieranie aktualnych danych oficjalnych i kontekstu Tavily wymaga dostępu do sieci; bez użytecznego klienta Tavily wykorzystywane są lokalne fixture'y demonstracyjne.

### Testy

Końcowy audyt TASK-06 potwierdził **130 testów** działających offline:

```bash
uv sync --group dev
uv run pytest -q
```

Oczekiwany wynik audytu: `130 passed`.

### Zrzuty ekranu raportu

Dwa miejsca na przyszłe zrzuty znajdują się w [sekcji angielskiej](#report-screenshots): pełny widok raportu HTML oraz sekcja przypisów i dowodów źródłowych. Odnośniki do obrazów zostaną dodane dopiero po umieszczeniu zrzutów w repozytorium.

### Zakres i ograniczenia

- Zakres danych jest celowo ograniczony do wskaźników obsługiwanych przez obecne konektory.
- Terminy publikacji są różne, dlatego jeden raport może obejmować okresy dzienne, miesięczne, kwartalne i roczne.
- Wycinki wyszukiwania są niezaufanym kontekstem, a nie autorytatywnymi obserwacjami liczbowymi ani instrukcjami dla agenta.
- Wynik LLM nie jest traktowany jako dane źródłowe; raporty powstają na podstawie zapisanych obserwacji i dowodów.
- Repozytorium jest prototypem portfolio i nie zawiera wdrożenia produkcyjnego, harmonogramu, publicznego API, dashboardu ani interaktywnych wykresów.
- Szczegóły architektury, kontraktu danych, migracji, jakości i polityki źródeł znajdują się w [indeksie dokumentacji](docs/INDEX.md).
