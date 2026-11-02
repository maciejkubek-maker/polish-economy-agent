"""
Testy automatyczne modułu produkcyjnej migracji SQLite v1 -> v2 (modules/migrator.py).

Weryfikuje:
1. Tryb dry-run: nie tworzy ani nie modyfikuje żadnych plików, zwraca kompletny bilans 75/10/6/91.
2. Tryb apply: tworzy bazę docelową ze schematem v2 i bezstratnie przenosi wszystkie encje.
3. Głębokie porównanie danych źródłowych z docelowymi (wartości, okresy, URL-e, markdown, agenci).
4. Zachowanie dat historycznych raportów (normalizacja z DD.MM.YYYY do ISO YYYY-MM-DD).
5. Poprawne pochodzenie źródeł (wskaźniki NBP -> SRC_LEGACY_2, GUS -> SRC_LEGACY_1) bez arbitralnych założeń.
6. Deterministyczne skróty SHA-256 dla wszystkich dowodów i raportów.
7. Izolacja konfliktów i wartości spornych (PKB -> CONFLICT, stopa bezrobocia r/r -> PENDING).
8. Idempotencja: ponowna migracja na istniejącej bazie docelowej nie tworzy duplikatów.
9. Bezpieczeństwo: próba nadpisania bazy źródłowej rzuca wyjątek ValueError.
10. Rollback transakcji w przypadku błędu w trakcie migracji.
11. Błędy nieistniejącej bazy źródłowej.
12. Działanie CLI migracji i weryfikacji.
13. Nienaruszalność oryginalnej bazy instance/economy_agent.db (73 728 bajtów, 75/10/6).
"""

import os
import sqlite3
import subprocess
import sys
import pytest

from modules.migrator import SQLiteV2Migrator, MigrationResult, normalize_iso_date, resolve_source_id

LEGACY_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "instance", "economy_agent.db")
SCHEMA_V2_SQL_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "sql", "schema_v2.sql")


def test_date_and_source_resolvers():
    """Testuje funkcje pomocnicze normalizacji dat i wyznaczania źródeł."""
    assert normalize_iso_date("18.09.2026") == "2026-09-18"
    assert normalize_iso_date("01.01.2025") == "2025-01-01"
    assert normalize_iso_date("2026-09-18") == "2026-09-18"
    assert normalize_iso_date(None) == "1970-01-01"

    assert resolve_source_id("NBP") == "SRC_LEGACY_2"
    assert resolve_source_id("Narodowy Bank Polski / Bankier.pl") == "SRC_LEGACY_2"
    assert resolve_source_id("GUS") == "SRC_LEGACY_1"
    assert resolve_source_id("Główny Urząd Statystyczny (GUS)") == "SRC_LEGACY_1"
    assert resolve_source_id("Bankier.pl") == "SRC_LEGACY_1"
    assert resolve_source_id("Trading Economics") == "SRC_LEGACY_1"


def test_migrator_dry_run_mode_does_not_create_or_modify_files(tmp_path):
    """Weryfikuje, że tryb dry-run nie tworzy pliku docelowego i poprawnie zlicza rekordy."""
    target_db = str(tmp_path / "test_dry_run_v2.db")
    migrator = SQLiteV2Migrator(
        source_db_path=LEGACY_DB_PATH,
        target_db_path=target_db,
        schema_sql_path=SCHEMA_V2_SQL_PATH,
    )

    result = migrator.migrate(dry_run=True)

    assert result.success is True
    assert result.dry_run is True
    assert result.sources_migrated == 10
    assert result.reports_migrated == 6
    assert result.indicators_migrated == 75
    assert result.evidence_migrated == 75
    assert result.candidates_migrated == 75
    assert result.legacy_map_entries == 91
    assert result.quality_events_created == 6
    assert result.conflicts_count == 4
    assert result.pending_count == 2
    assert result.verified_count == 69

    # Plik docelowy NIE MOŻE powstać w trybie dry-run
    assert not os.path.exists(target_db)


def test_migrator_apply_creates_target_database_with_exact_counts(tmp_path):
    """Weryfikuje pełną migrację fizyczną z zapisem do nowej bazy docelowej."""
    target_db = str(tmp_path / "test_applied_v2.db")
    migrator = SQLiteV2Migrator(
        source_db_path=LEGACY_DB_PATH,
        target_db_path=target_db,
        schema_sql_path=SCHEMA_V2_SQL_PATH,
    )

    result = migrator.migrate(dry_run=False)

    assert result.success is True
    assert result.dry_run is False
    assert os.path.exists(target_db)

    # Sprawdzenie bezpośrednie w bazie docelowej
    conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
    cur = conn.cursor()

    assert cur.execute("SELECT count(*) FROM source_registry").fetchone()[0] == 10
    assert cur.execute("SELECT count(*) FROM reports").fetchone()[0] == 6
    assert cur.execute("SELECT count(*) FROM source_evidence").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM extracted_candidates").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM legacy_migration_map").fetchone()[0] == 91
    assert cur.execute("SELECT count(*) FROM quality_events").fetchone()[0] == 6

    conn.close()


def test_migrator_deep_field_comparison_source_vs_target(tmp_path):
    """
    Głębokie porównanie danych źródłowych z docelowymi:
    Weryfikuje treść każdego z 75 wskaźników, 10 źródeł i 6 raportów.
    """
    target_db = str(tmp_path / "test_deep_check.db")
    migrator = SQLiteV2Migrator(
        source_db_path=LEGACY_DB_PATH,
        target_db_path=target_db,
    )
    result = migrator.migrate(dry_run=False)
    assert result.success is True

    integrity_report = migrator.verify_integrity(target_db)
    assert integrity_report["counts_match"] is True
    assert integrity_report["all_75_indicators_content_matched"] is True
    assert integrity_report["nbp_source_assignment_correct"] is True
    assert integrity_report["all_6_reports_content_matched"] is True
    assert integrity_report["quality_conflicts_isolated"] is True
    assert integrity_report["overall_integrity_passed"] is True


def test_migrator_preserves_historical_report_dates_and_sha256_snapshot(tmp_path):
    """Weryfikuje zachowanie oryginalnych dat raportów i obecność 64-znakowego hasha SHA-256."""
    target_db = str(tmp_path / "test_reports.db")
    migrator = SQLiteV2Migrator(source_db_path=LEGACY_DB_PATH, target_db_path=target_db)
    migrator.migrate(dry_run=False)

    conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
    cur = conn.cursor()
    rows = cur.execute("SELECT report_id, report_date, data_snapshot_hash, report_markdown FROM reports").fetchall()
    conn.close()

    assert len(rows) == 6
    for rep_id, r_date, snap_hash, r_md in rows:
        assert r_date == "2026-09-18"
        assert len(snap_hash) == 64
        assert snap_hash != "legacy_hash"
        assert len(r_md) > 100


def test_migrator_accurate_source_provenance_and_evidence_hashes(tmp_path):
    """Weryfikuje pochodzenie źródeł oraz brak sztucznych prefiksów hash_."""
    target_db = str(tmp_path / "test_sources.db")
    migrator = SQLiteV2Migrator(source_db_path=LEGACY_DB_PATH, target_db_path=target_db)
    migrator.migrate(dry_run=False)

    conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
    cur = conn.cursor()

    # NBP vs GUS
    nbp_rows = cur.execute("SELECT evidence_id, source_id, content_hash FROM source_evidence WHERE source_id = 'SRC_LEGACY_2'").fetchall()
    gus_rows = cur.execute("SELECT evidence_id, source_id, content_hash FROM source_evidence WHERE source_id = 'SRC_LEGACY_1'").fetchall()
    conn.close()

    assert len(nbp_rows) == 5
    assert len(gus_rows) == 70
    assert len(nbp_rows) + len(gus_rows) == 75

    for evi_id, src_id, c_hash in nbp_rows + gus_rows:
        assert len(c_hash) == 64
        assert not c_hash.startswith("hash_")


def test_migrator_idempotency_on_target_database(tmp_path):
    """Weryfikuje, że ponowne uruchomienie migracji na tej samej bazie nie tworzy duplikatów."""
    target_db = str(tmp_path / "test_idempotency.db")
    migrator = SQLiteV2Migrator(source_db_path=LEGACY_DB_PATH, target_db_path=target_db)

    # Przebieg 1
    res1 = migrator.migrate(dry_run=False)
    assert res1.success is True

    # Przebieg 2 na tej samej bazie
    res2 = migrator.migrate(dry_run=False)
    assert res2.success is True

    conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
    cur = conn.cursor()

    assert cur.execute("SELECT count(*) FROM source_registry").fetchone()[0] == 10
    assert cur.execute("SELECT count(*) FROM reports").fetchone()[0] == 6
    assert cur.execute("SELECT count(*) FROM source_evidence").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM extracted_candidates").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM quality_events").fetchone()[0] == 6
    assert cur.execute("SELECT count(*) FROM legacy_migration_map").fetchone()[0] == 91

    conn.close()


def test_migrator_prohibits_overwriting_source_database():
    """Weryfikuje, że próba użycia bazy źródłowej jako docelowej jest bezwzględnie blokowana."""
    with pytest.raises(ValueError) as exc:
        SQLiteV2Migrator(
            source_db_path=LEGACY_DB_PATH,
            target_db_path=LEGACY_DB_PATH,
        )
    assert "nadpisywanie bazy produkcyjnej jest zablokowane" in str(exc.value).lower()


def test_migrator_error_handling_missing_source_database(tmp_path):
    """Weryfikuje reakcję na brak pliku bazy źródłowej."""
    missing_source = str(tmp_path / "non_existent_source.db")
    target_db = str(tmp_path / "target.db")
    with pytest.raises(FileNotFoundError):
        SQLiteV2Migrator(
            source_db_path=missing_source,
            target_db_path=target_db,
        )


def test_migrator_transaction_rollback_on_failure(tmp_path, monkeypatch):
    """Weryfikuje wycofanie transakcji (rollback) i usunięcie pliku w przypadku awarii."""
    target_db = str(tmp_path / "test_rollback_v2.db")
    migrator = SQLiteV2Migrator(
        source_db_path=LEGACY_DB_PATH,
        target_db_path=target_db,
    )

    # Symulujemy awarię w trakcie pętli wskaźników
    original_normalize = normalize_iso_date

    def failing_normalize(date_str):
        raise RuntimeError("Symulowany krytyczny błąd formatu w transakcji")

    monkeypatch.setattr("modules.migrator.normalize_iso_date", failing_normalize)

    result = migrator.migrate(dry_run=False)

    assert result.success is False
    assert any("Symulowany krytyczny błąd" in err for err in result.errors)
    # Nowo tworzony plik docelowy powinien zostać usunięty / wycofany
    assert not os.path.exists(target_db)


def test_migrator_cli_dry_run_and_apply(tmp_path):
    """Weryfikuje uruchamianie migratora przez CLI."""
    target_db = str(tmp_path / "cli_test_v2.db")

    # 1. CLI --dry-run (domyślny)
    cmd_dry = [
        sys.executable,
        "-m",
        "modules.migrator",
        "--source",
        LEGACY_DB_PATH,
        "--target",
        target_db,
    ]
    proc_dry = subprocess.run(cmd_dry, capture_output=True, text=True, check=True)
    assert "SUKCES (DRY-RUN)" in proc_dry.stdout
    assert not os.path.exists(target_db)

    # 2. CLI --apply
    cmd_apply = [
        sys.executable,
        "-m",
        "modules.migrator",
        "--source",
        LEGACY_DB_PATH,
        "--target",
        target_db,
        "--apply",
    ]
    proc_apply = subprocess.run(cmd_apply, capture_output=True, text=True, check=True)
    assert "SUKCES (APPLY)" in proc_apply.stdout
    assert os.path.exists(target_db)

    # 3. CLI --verify
    cmd_verify = [
        sys.executable,
        "-m",
        "modules.migrator",
        "--source",
        LEGACY_DB_PATH,
        "--target",
        target_db,
        "--verify",
    ]
    proc_verify = subprocess.run(cmd_verify, capture_output=True, text=True, check=True)
    assert "[OK] overall_integrity_passed: True" in proc_verify.stdout


def test_original_database_remains_strictly_untouched():
    """Weryfikuje niezmiennik bazy produkcyjnej (73 728 bajtów, 75/10/6)."""
    assert os.path.exists(LEGACY_DB_PATH)
    assert os.path.getsize(LEGACY_DB_PATH) == 73728

    conn = sqlite3.connect(f"file:{LEGACY_DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()
    assert cur.execute("SELECT count(*) FROM collected_indicators").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM trusted_sources").fetchone()[0] == 10
    assert cur.execute("SELECT count(*) FROM generated_reports").fetchone()[0] == 6
    conn.close()
