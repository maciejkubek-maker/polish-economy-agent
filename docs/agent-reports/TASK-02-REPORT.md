# TASK-02 — raport Antigravity / Codex

**Status:** `DONE`  
**Branch:** `refactor/02-html-security`  
**Commit SHA:** `218725d22227d86f78fbb984fa5b4b1a477382ae`  
**PR:** `https://github.com/maciejkubek-maker/polish-economy-agent/pull/2`  
**Data:** 2026-11-02  

## Co wykonałem
- Zaimplementowano bezpieczne renderowanie tekstu raportu w produkcyjnej funkcji `app.format_report_html`:
  - Sanityzacja / ucieczka znaków specjalnych HTML za pomocą `html.escape(str(text), quote=True)` przed przetwarzaniem reguł Markdown.
  - Neutralizacja wszystkich znaczników HTML (`<script>`, `<img>`, `<iframe>`, `<style>`, `<object>`, `<embed>`) oraz atrybutów obsługi zdarzeń (`onerror`, `onload`, `onclick`).
  - Bezpieczne parsowanie odnośników URL z walidacją schematu (`http` / `https`) za pomocą `urllib.parse.urlparse`, uniemożliwiające użycie pseudoprotokołów `javascript:`, `data:`, `vbscript:`.
  - Prawidłowe zachowanie interpunkcji kończącej zdania przy adresach URL (np. kropka po adresie nie staje się częścią atrybutu `href`).
- Zaimplementowano bezpieczne osadzanie parametru kraju w szablonie strony w `app.build_html_template` (`safe_country = html.escape(str(country or ""), quote=True)`), chroniąc sekcje `<title>` oraz `<div class="footer">`.
- Wdrożono minimalną leniwą inicjalizację bazy danych SQLite w `app.py`:
  - Usunięto globalne wywołanie `db = EconomyDatabase()` na poziomie modułu, które powodowało niepożądane operacje na `instance/economy_agent.db` podczas samego importu modułu.
  - Dodano funkcje `get_db()` oraz `set_db(database)` umożliwiające wstrzykiwanie bazy testowej / izolowanej.
- Przepisano zestaw testów bezpieczeństwa w `tests/test_html_security.py`:
  - Usunięto testy asercyjnie oczekujące przepuszczenia podatności oraz usunięto funkcje pomocnicze `proposed_*`.
  - Wszystkie 13 testów bezpieczeństwa weryfikuje teraz bezpośrednio produkcyjne funkcje `app.format_report_html`, `app.build_html_template` oraz endpoint serwera Flask (`server.test_client()`).
  - Dodano testy na encje HTML, cudzysłowy, znaki `&` w parametrach URL, polskie znaki diakrytyczne, wartości `None`/puste, oraz brak efektu ubocznego przy imporcie `app`.

## Zmienione pliki
| Ścieżka | Opis |
|---|---|
| `app.py` | Leniwa inicjalizacja bazy SQLite (`get_db`, `set_db`), sanityzacja HTML (`html.escape`), walidacja schematów URL w `format_report_html` i `build_html_template`. |
| `tests/test_html_security.py` | Przepisanie suite testów na bezpośrednie testowanie funkcji produkcyjnych, test endpointu Flask, testy krawędziowe (Unicode, ampersandy, brak treści, leniwa baza). |
| `docs/agent-reports/TASK-02-REPORT.md` | Niniejszy raport z realizacji zadania TASK-02. |

## Testy i kontrole
| Polecenie | Status PASSED/FAILED/NOT_RUN | Wynik |
|---|---|---|
| `uv run pytest -q` | **PASSED** | 48 passed w 0.76s (100% testów zielonych, w tym 13 testów bezpieczeństwa HTML). |

## Stan danych i bezpieczeństwa
- Czy zmodyfikowano `instance/economy_agent.db`? **NIE**. Baza produkcyjna pozostała nienaruszona (75 wskaźników, 10 źródeł, 6 raportów, 73 728 bajtów).
- Czy były wywołania płatnych API? **NIE**. Wszystkie testy wykonano całkowicie offline.
- Czy pozostają znane podatności? **FIXED**: Podatność Stored / Reflected XSS w renderowaniu raportu oraz parametru kraju została całkowicie wyeliminowana w kodzie produkcyjnym.

## Ryzyka / regresje / ograniczenia
- Parser Markdown w `app.format_report_html` jest celowo prostym, bezpiecznym konwerterem regułowym (`#`, `##`, `###`, `**bold**`, `[1]`, `http/https`). Nie obsługuje zaawansowanych tabel ani zagnieżdżonych list Markdown, co jest wystarczające dla obecnych raportów LLM i eliminuje konieczność wprowadzania ciężkich bibliotek zewnętrznych.
- Branch bazowy: `refactor/02-html-security` został utworzony na bazie `refactor/01-safety-baseline` (PR #1 jest w stanie Draft). Po scaleniu PR #1 do `main`, PR #2 zostanie automatycznie zrebase'owany na `main`.

## Decyzje wymagane
- Brak nowych blokujących decyzji. Wszystkie ustalenia zrealizowano zgodnie z zatwierdzonym zakresem.

## Następny sugerowany krok
- Code review i zatwierdzenie PR #2 (`refactor/02-html-security`).
- Przejście do **TASK-03** — Projekt katalogu wskaźników i nowego schematu bazy danych (`tasks/TASK_03_SCHEMA_DESIGN.md`).

## JSON status
```json
{
  "task_id": "TASK-02",
  "status": "READY_FOR_REVIEW",
  "branch": "refactor/02-html-security",
  "commit_sha": "218725d22227d86f78fbb984fa5b4b1a477382ae",
  "pull_request": "https://github.com/maciejkubek-maker/polish-economy-agent/pull/2",
  "tests": {"status": "PASSED", "passed": 48, "failed": 0},
  "files_changed": [
    "app.py",
    "tests/test_html_security.py",
    "docs/agent-reports/TASK-02-REPORT.md"
  ],
  "risks": [],
  "requires_decision": []
}
```
