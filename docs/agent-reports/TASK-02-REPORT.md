# TASK-02 — raport Antigravity / Codex

**Status:** `DONE`  
**Branch:** `refactor/02-html-security`  
**Commit SHA:** `62fbbb603a12a5598cf429d81d77a5e95bb2ae32`  
**PR:** `https://github.com/maciejkubek-maker/polish-economy-agent/pull/2`  
**Data:** 2026-11-02  

## Co wykonałem
- **Sanityzacja HTML w kodzie produkcyjnym (`app.format_report_html`):**
  - Wprowadzono ucieczkę znaków specjalnych HTML za pomocą `html.escape(str(text), quote=True)` przed aplikowaniem znaczników Markdown.
  - Zneutralizowano znaczniki HTML (`<script>`, `<img>`, `<iframe>`, `<style>`, `<object>`, `<embed>`) oraz atrybuty obsługi zdarzeń (`onerror`, `onload`, `onclick`).
  - Zaimplementowano bezpieczne parsowanie odnośników URL za pomocą biblioteki standardowej `urllib.parse.urlparse`: dozwolone są wyłącznie schematy `http://` oraz `https://`. Pseudoprotokoły (`javascript:`, `data:`, `vbscript:`) są odrzucane i nie tworzą odnośników.
  - Prawidłowo obsłużono znaki interpunkcyjne na końcu adresów URL (kropki, przecinki, wykrzykniki nie wchodzą w skład atrybutu `href`).
- **Zabezpieczenie szablonu (`app.build_html_template`):**
  - Escapowanie parametru `country` za pomocą `html.escape` zapobiega wstrzyknięciom kodu w sekcjach `<title>` oraz `<div class="footer">`.
- **Leniwa inicjalizacja bazy SQLite w `app.py`:**
  - Usunięto natychmiastową inicjalizację `db = EconomyDatabase()` na poziomie modułu.
  - Wprowadzono funkcje `get_db()` oraz `set_db(database)`, co gwarantuje brak efektów ubocznych (brak otwierania połączeń SQLite) przy samym imporcie modułu `app`.
- **Poprawki po Code Review (Status CHANGES REQUESTED):**
  1. *Usunięcie pozornego testu:* Usunięto tautologię `assert get_db() is not None or True`. Zastąpiono ją dwoma rygorystycznymi testami:
     - `test_import_and_rendering_does_not_instantiate_or_touch_database`: szpieg na `EconomyDatabase.__init__` weryfikujący brak wywołań konstruktora bazy przy renderowaniu HTML.
     - `test_isolated_process_import_app_does_not_create_db_connection`: test w osobnym procesie Pythona monitorujący wywołania `sqlite3.connect` i potwierdzający stan `_db is None` oraz 0 połączeń do SQLite.
  2. *Izolacja stanu `_db` między testami:* Dodano fixture `reset_app_database` (`autouse=True`), która zapamiętuje i przywraca stan `app._db` przed i po każdym teście, zapobiegając wzajemnemu wpływowi testów na siebie.
  3. *Weryfikacja i testy fallbacku `report.html`:*
     - Sprawdzono bezpieczeństwo ścieżki pliku (ścieżka jest zakodowana na stałe, brak ryzyka Path Traversal).
     - Dodano test `test_flask_endpoint_fallback_to_file_when_db_has_no_report` weryfikujący poprawne serwowanie pliku statycznego, gdy baza nie zawiera raportu.
     - Dodano test `test_flask_endpoint_404_when_db_and_file_missing` weryfikujący czystą odpowiedź 404 w przypadku braku raportu w bazie i braku pliku na dysku.
     - Dodano test `test_save_report_to_html_produces_sanitized_file` potwierdzający, że statyczny eksport do pliku HTML generuje oczyszczony, bezpieczny kod.

## Zmienione pliki
| Ścieżka | Opis |
|---|---|
| `app.py` | Leniwa inicjalizacja bazy SQLite (`get_db`, `set_db`), sanityzacja HTML (`html.escape`), walidacja schematów URL w `format_report_html` i `build_html_template`. |
| `tests/test_html_security.py` | 17 testów bezpieczeństwa: bezpośrednie testy funkcji produkcyjnych, testy w osobnym procesie, testy fallbacku do pliku i 404, fixture przywracająca stan bazy. |
| `docs/agent-reports/TASK-02-REPORT.md` | Raport wykonawczy uwzględniający poprawki po code review. |

## Testy i kontrole
| Polecenie | Status PASSED/FAILED/NOT_RUN | Wynik |
|---|---|---|
| `uv run pytest -q` | **PASSED** | 52 passed w 1.15s (100% testów zielonych, w tym 17 testów bezpieczeństwa HTML i izolacji). |

## Stan danych i bezpieczeństwa
- Czy zmodyfikowano `instance/economy_agent.db`? **NIE**. Baza produkcyjna pozostała nienaruszona (75 wskaźników, 10 źródeł, 6 raportów, 73 728 bajtów).
- Czy były wywołania płatnych API? **NIE**. Wszystkie testy wykonano całkowicie offline.
- Czy pozostają znane podatności? **FIXED**: Podatność Stored / Reflected XSS w renderowaniu raportu oraz parametru kraju została całkowicie wyeliminowana w kodzie produkcyjnym.
- Efekty uboczne importu `app.py`: **FIXED**: Potwierdzone testem wieloprocesowym, że import `app` i renderowanie HTML nie otwierają połączenia do SQLite.

## Ryzyka / regresje / ograniczenia
- Parser Markdown w `app.format_report_html` celowo nie obsługuje zaawansowanych tabel ani zagnieżdżonych list (skupia się na nagłówkach, pogrubieniach, przypisach numerycznych i bezpiecznych linkach URL). Jest to zgodne z zakresem i zapobiega wprowadzaniu zewnętrznych zależności.
- Zależność bazowa: PR #2 bazuje na commitach z PR #1 (będącego w stanie Draft). Po zmergowaniu PR #1 do `main`, PR #2 zostanie płynnie zintegrowany.

## Decyzje wymagane
- Brak nowych decyzji blokujących. Gotowość do ponownego review PR #2.

## Następny sugerowany krok
- Ponowne code review PR #2 i zatwierdzenie.
- Po akceptacji: przejście do **TASK-03** — Projekt katalogu wskaźników i nowego schematu bazy danych.

## JSON status
```json
{
  "task_id": "TASK-02",
  "status": "READY_FOR_REVIEW",
  "branch": "refactor/02-html-security",
  "commit_sha": "62fbbb603a12a5598cf429d81d77a5e95bb2ae32",
  "pull_request": "https://github.com/maciejkubek-maker/polish-economy-agent/pull/2",
  "tests": {"status": "PASSED", "passed": 52, "failed": 0},
  "files_changed": [
    "app.py",
    "tests/test_html_security.py",
    "docs/agent-reports/TASK-02-REPORT.md"
  ],
  "risks": [],
  "requires_decision": []
}
```
