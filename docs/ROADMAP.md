# ROADMAP — etapowa refaktoryzacja Polish Economy Agent

## Status na 2026-11-02
- PR #1 `refactor/01-safety-baseline`: otwarty Draft, 43 testy zgłoszone przez Codexa jako PASSED. Nie jest naprawą XSS.
- Zmieniamy architekturę **ewolucyjnie**, bez big-bang rewrite.

| Kolejność | Zadanie / branch (propozycja) | Zakres | Kryterium wyjścia |
|---|---|---|---|
| 0 | Review PR #1 | Zweryfikować diff, testy i backup | merge tylko za zgodą właściciela |
| 1 | TASK-02 `refactor/02-html-security` | Bezpieczny renderer HTML + testy produkcyjnych funkcji | brak przechodzącego XSS, regresja zielona |
| 2 | TASK-03 `design/03-data-contract` | Projekt katalogu wskaźników, schematu, migracji i ADR | zatwierdzone kontrakty, bez migracji |
| 3 | TASK-04 `refactor/04-storage-migration` | Nowy schemat + bezstratna migracja copy-to-copy | wszystkie 75 legacy wejść zachowane, idempotencja |
| 4 | TASK-05 `feat/05-official-data-adapters` | Pierwsze oficjalne API i testy stubowane | identyfikowalny dataset, sprawdzona jednostka/okres |
| 5 | TASK-06 `feat/06-web-evidence` | Zachowanie i ulepszenie Tavily, dowody źródłowe | deduplikacja URL, daty, retry i źródła |
| 6 | TASK-07 `feat/07-data-validation` | Reguły, konflikty, freshness per wskaźnik | niezweryfikowane nie zasilają faktów raportu |
| 7 | TASK-08 `feat/08-multi-agent-analysis` | Niezależne interpretacje GPT/Gemini na validated | raport odróżnia fakty, opinie i rozbieżności |
| 8 | TASK-09 `feat/09-report-ui` | Raportowanie, bezpieczne HTML, widoczność źródeł | użyteczny raport + dokumentacja portfolio |
| 9 | TASK-10 `chore/10-release-readiness` | README, sample report, CI, opcjonalny deployment | demonstracja gotowa dla rekrutera |

## Warunki przejścia do następnego zadania
1. Aktualny PR przeszedł review, testy i ma potwierdzone rollback/compatibility, jeśli dotyczy danych.
2. Nie rozwijamy kolejnej warstwy, jeżeli otwarty jest problem krytyczny bezpieczeństwa uniemożliwiający bezpieczne testy/demonstrację.
3. Jeśli PR #1 nie jest scalony, kolejny branch twórz od właściwego wspólnego punktu z uwzględnieniem testów albo poczekaj na merge — nie zakładaj domyślnie, że `main` zawiera `tests/`.
4. Odrębna decyzja właściciela wymagana dla aktywacji płatnych API, migracji realnych danych, zmian wdrożeniowych, usunięcia śledzonej bazy i merge.

## Zakres minimalnego działającego produktu
W pierwszej wersji produkcyjno-demonstracyjnej wystarczą wybrane wskaźniki z oficjalnymi danymi, wyszukiwanie publikacji, walidacja, spójny raport i testy offline. Nie próbujemy budować od razu wszystkich wskaźników gospodarki.