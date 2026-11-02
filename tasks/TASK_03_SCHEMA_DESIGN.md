# CODEX TASK-03 — projekt katalogu wskaźników i nowego schematu (bez migracji)

**Repo:** `maciejkubek-maker/polish-economy-agent`  
**Proponowany branch:** `design/03-data-contract`  
**Warunek startu:** zatwierdzenie rezultatu TASK-02 / ustalenie bazy PR.

## Cel
Przygotować projekt warstwy danych dla API + Tavily + LLM, bez zmiany produkcyjnej bazy, ekstraktorów lub wykonywania migracji.

## Materiały wejściowe
`docs/ARCHITECTURE.md`, `docs/DATA_CONTRACT.md`, `docs/SOURCE_POLICY.md`, `docs/MIGRATION.md`, `docs/DECISIONS.md`, `docs/PR_01_REVIEW.md`, `docs/BASELINE.md`.

## Zrób
1. Zaproponuj konkretny schemat SQLite DDL v2: katalog wskaźników, rejestr źródeł, metadane pobrań/dowodów, kandydaci LLM, obserwacje wersjonowane, incydenty jakości, raporty.
2. Zaprojektuj słownik aliasów wskaźników z metodologią i ograniczeniami automatycznego mapowania. Oddziel bezrobocie rejestrowane od BAEL; CPI r/r od m/m; PKB r/r od q/q.
3. Zaproponuj typ decimal i zasady reprezentacji jednostek, częstotliwości oraz dat w UTC.
4. Stwórz **konceptualną** tabelę źródeł dla pierwszego zestawu wskaźników; nie deklaruj niezweryfikowanego API jako istniejącego.
5. Zdefiniuj reguły idempotencji, rewizji, konfliktów, jakości i politykę cache per wskaźnik.
6. Przygotuj mapę starych 75 rekordów na kandydatów w *trybie odczytu*; policz przypadki wymagające decyzji, nie nadpisuj starej bazy.
7. Przedstaw plan wdrożenia w mniejszych PR-ach i listę pytań do właściciela.

## Wynik
Pliki projektowe `docs/SCHEMA_V2_PROPOSAL.md`, `docs/MIGRATION_V2_PLAN.md`, opcjonalnie `docs/sql/schema_v2.sql` (DDL demonstracyjny, **nie wykonywać automatycznie**), oraz lista otwartych decyzji.

## Ograniczenia
Bez destrukcyjnych zmian, bez dotykania realnej bazy, bez nowych płatnych API, bez przepisywania aplikacji. Jeśli nie da się rozstrzygnąć metodyki lub okresu: oznacz jako niepewne.

## Kryteria akceptacji
- [ ] Każde pole i klucz modelu ma opis oraz testowalną regułę integralności.
- [ ] Wersje odczytów są append-only; brak przypadkowego zacierania historii.
- [ ] Jest plan odtworzenia i rollback.
- [ ] Raport mapowania legacy dokumentuje komplet 75 wejść i przypadki niejednoznaczne.
- [ ] Decyzja o finalnym schemacie pozostaje po stronie właściciela po review.

Draft PR z dokumentacją, bez merge.
