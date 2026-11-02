# Indeks dokumentacji — Polish Economy Agent

Ten zestaw dokumentacji opisuje uzgodnione reguły współpracy oraz plan refaktoryzacji. Projekty techniczne oznaczone jako PROPOSED wymagają zatwierdzenia przed implementacją.

## Przeczytaj w tej kolejności
1. [`../AGENTS.md`](../AGENTS.md) — reguły pracy Codexa.
2. [`PR_01_REVIEW.md`](PR_01_REVIEW.md) — przegląd Draft PR i ostrzeżenia.
3. [`DECISIONS.md`](DECISIONS.md) — uzgodnione decyzje i otwarte pytania.
4. [`ARCHITECTURE.md`](ARCHITECTURE.md) — architektura docelowa.
5. [`DATA_CONTRACT.md`](DATA_CONTRACT.md) — projekt modelu danych i migracji.
6. [`SOURCE_POLICY.md`](SOURCE_POLICY.md) — reguły API + Tavily.
7. [`ROADMAP.md`](ROADMAP.md) — kolejność etapów.
8. [`QUALITY_GATES.md`](QUALITY_GATES.md) — testy, bezpieczeństwo i akceptacja.
9. [`MIGRATION.md`](MIGRATION.md) — bezstratna migracja SQLite.

## Zadania
- [`../tasks/TASK_02_SECURITY.md`](../tasks/TASK_02_SECURITY.md) — następne zadanie wykonawcze po review PR #1.
- [`../tasks/TASK_03_SCHEMA_DESIGN.md`](../tasks/TASK_03_SCHEMA_DESIGN.md) — projekt techniczny bez migracji.
- [`../templates/TASK_TEMPLATE.md`](../templates/TASK_TEMPLATE.md) — szablon następnych zadań.

## Fakty bazowe
- Repo: https://github.com/maciejkubek-maker/polish-economy-agent
- PR #1: https://github.com/maciejkubek-maker/polish-economy-agent/pull/1
- Pierwotny commit PR #1: `fbf9eef111887d2e593750c9be2e8b53278d439e`
- Baza: 75 odczytów, 10 źródeł, 6 raportów; 73 728 B.
- Codex zaraportował 43/43 testy offline, bez niezależnego powtórzenia przez recenzenta.
- Podatność XSS nadal istnieje w implementacji produkcyjnej PR #1: testy ją dokumentują, ale nie naprawiają.

## Rozróżnienia
`AGENTS.md` to reguły; `DECISIONS.md` — wybory zatwierdzone i otwarte pytania; `ARCHITECTURE.md` oraz `DATA_CONTRACT.md` — projekty do potwierdzenia; `tasks/` — specyfikacje zadań. Nie traktuj projektowanych tabel ani API jako już wdrożonych.
