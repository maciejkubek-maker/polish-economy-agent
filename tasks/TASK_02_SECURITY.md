# CODEX TASK-02 — naprawa bezpieczeństwa HTML

**Repo:** `maciejkubek-maker/polish-economy-agent`  
**Proponowany branch:** `refactor/02-html-security`  
**Warunek startu:** skontrolowany PR #1 i dostęp do jego suite; najlepiej po merge PR #1 do `main`. Gdy nadal Draft, zgłoś zależność zamiast pracować na bazie nieposiadającej testów.

## Cel
Usunąć podatność na wstrzykiwanie niezaufanego HTML/JavaScript w **produkcyjnych** `app.format_report_html` i `app.build_html_template`, zachowując nagłówki, tekst, przypisy i bezpieczne linki do źródeł.

## Stan potwierdzony
PR #1 ma 43 testy. W `tests/test_html_security.py` cztery testy *pozytywnie potwierdzają podatność*, a cztery sprawdzają osobne funkcje `proposed_*`. Kod produkcyjny nie został poprawiony.

## Zakres
1. Wprowadź bezpieczne renderowanie Markdown do HTML. **Nie składaj HTML z nieescapowanych fragmentów**. Dopuszczalne: sprawdzona biblioteka renderer + bezpieczna polityka HTML albo poprawnie zaprojektowane escapowanie i wstawianie dozwolonych tagów.
2. Escapuj `country` w tytule i stopce. URL w atrybucie `href` obsługuj bezpiecznie, waliduj schemat `http`/`https`, unikaj `javascript:`/atrybutów zdarzeń.
3. Przepisz testy tak, żeby testowały **produkcję** i wymagany stan bezpieczny. Nie pozostawiaj testu, który uważa przepuszczenie `<script>` za sukces. Historyczny przykład może być w dokumentacji albo test oznaczony `xfail` wyłącznie jeśli ma cel.
4. Przetestuj `<script>`, `img onerror`, `iframe`, niebezpieczne linki, encje HTML, cudzysłowy, URL z `&`, znaki Unicode oraz brak/NULL treści.
5. Utrzymaj poprawne renderowanie znanych przykładów Markdown z raportu oraz cytowania `[1]`.
6. Usuń lub wyizoluj skutek uboczny importu `app.py`: inicjalizacja `EconomyDatabase()` dotyka ścieżki rzeczywistej bazy przed użyciem fixture `tmp_path`. Testy bezpieczeństwa nie powinny wymagać zapisu do pliku bazowego.
7. Jeśli potrzeba nowej zależności, uzasadnij ją, zaktualizuj lockfile i przetestuj offline.

## Poza zakresem
- Nowy schemat SQLite, migracja danych, modyfikacja analizy makroekonomicznej, zmiany Tavily/GPT/Gemini, sieciowe testy live.
- Zmiana istniejącej bazy i raportów w historii Git.

## Kryteria akceptacji
- [ ] W wynikowym HTML żaden wstrzyknięty skrypt/handler/iframe nie jest wykonywalny.
- [ ] Testy `app.format_report_html`, `app.build_html_template` i endpointu Flask korzystają z faktycznej implementacji.
- [ ] Dotychczasowe regresje przechodzą po właściwym dostosowaniu ich do bezpiecznego stanu.
- [ ] Brak płatnych wywołań API i brak zapisu do `instance/economy_agent.db`.
- [ ] W PR dokumentacja: ryzyko, sposób naprawy, testy, rollback.

## Zakończenie
Draft PR z tytułem `security: sanitize report rendering and update regression tests`; zwróć link, SHA, zmienione pliki, wyniki pytest i ograniczenia. **Nie wykonuj merge.**