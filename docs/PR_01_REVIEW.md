# Code review — PR #1 Safety Baseline

**Stan na:** 2026-11-02  
**PR:** https://github.com/maciejkubek-maker/polish-economy-agent/pull/1  
**Branch:** `refactor/01-safety-baseline`  
**Commit:** `fbf9eef111887d2e593750c9be2e8b53278d439e`  
**Status GitHub:** Draft, open; na dzień przeglądu nie scalono.

## Potwierdzone z repozytorium
- PR zawiera 13 zmienionych plików, dokument `docs/BASELINE.md`, siedem modułów testowych, fixture `tests/conftest.py`, zmiany `pyproject.toml`, `uv.lock`, `.gitignore`.
- Nie zmieniono `app.py`, `modules/database.py` ani ekstraktorów — to odpowiada zakresowi *Safety Baseline*, ale nie usuwa wykrytych błędów.
- `docs/BASELINE.md` potwierdza liczniki bazy: 75 / 10 / 6; odpowiadają analizie dostępnej kopii bazy.
- Kod `tests/test_html_security.py` posiada **cztery testy, które potwierdzają, że podatne renderowanie wciąż przepuszcza złośliwy HTML**. Kolejne cztery testują osobne funkcje `proposed_*`, a **nie produkcyjne** `app.format_report_html` i `app.build_html_template`.
- `tests/conftest.py` podstawia fikcyjne klucze do zmiennych środowiskowych, by umożliwić import kodu offline. To nie rozwiązuje problemu wymuszania kluczy w `config.py`.
- **Uwaga o izolacji:** `tests/test_html_security.py` importuje `app`, a `app.py` podczas importu tworzy `EconomyDatabase()`, co uruchamia `init_db()` na ścieżce `instance/economy_agent.db`. Dlatego stwierdzenie, że wszystkie testy są całkowicie izolowane od tej bazy, jest zbyt szerokie: testy większości operacji bazodanowych używają `tmp_path`, ale import aplikacji ma potencjalny efekt uboczny. Należy to wyeliminować lub zweryfikować na oddzielnym środowisku przed merge.
- `test_baseline_database_integrity` wymaga stałych 75/10/6; po legalnej migracji bazy test ten musi operować na zarchiwizowanej niezmiennej fixture, a nie na przyszłej bazie roboczej.

## Wyniki wykonania
Codex dostarczył log pytest 43 passed (Windows/Python 3.11). Recenzent sprawdził obecność testów i ich treść, **nie wykonał ponownie całej suite**. Zielony wynik nie oznacza, że produkcyjny XSS został naprawiony.

## Ocena
**Zaakceptować jako dokumentację stanu wyjściowego po rutynowym przeglądzie diffu/uruchomieniu CI; NIE traktować jako naprawy bezpieczeństwa.** Ewentualne scalenie PR #1 jest decyzją właściciela. Następny PR powinien naprawić XSS i zmienić asercje testów na oczekiwane zachowanie bezpieczne.

## Lista kontrolna przed merge PR #1
- [ ] Zweryfikować pełny diff na GitHubie i brak przypadkowo dodanych sekretów.
- [ ] Wykonać `uv run pytest -q` (najlepiej również na czystym checkout/CI).
- [ ] Potwierdzić backup bazy **poza repo**, z możliwością otwarcia odtworzonej kopii.
- [ ] Potwierdzić, że XSS jest jawnie opisany jako otwarty problem, a nie naprawiony.
- [ ] Zweryfikować skutek uboczny importu `app` (inicjalizacja oryginalnego pliku SQLite) i zdecydować o izolacji także testów HTML.
- [ ] Zdecydować, czy test stałych liczników bazy pozostaje tylko w archiwalnej fixture.
- [ ] Dopiero po przeglądzie rozważyć merge.

## Otwarta uwaga do przyszłej pracy
Format JSON przekazywany do automatycznych raportów musi odróżniać `PASSED` testów regresyjnych od `SECURITY_FIXED`; to różne stany. Nie zamykać zgłoszenia podatności na podstawie testów wykrywających jej obecność.