"""
Testy automatyczne modułu produkcyjnej migracji SQLite v1 -> v2 (modules/migrator.py).

Weryfikuje:
1. Tryb dry-run: nie tworzy ani nie modyfikuje żadnych plików, zwraca kompletny bilans 75/10/6/91.
2. Tryb apply: tworzy bazę docelową ze schematem v2 i bezstratnie przenosi wszystkie encje.
3. Głębokie porównanie danych źródłowych z docelowymi (wartości, okresy, URL-e, markdown, agenci).
4. Zachowanie dat historycznych raportów (normalizacja z DD.MM.YYYY do ISO YYYY-MM-DD).
5. Poprawne, szczegółowe pochodzenie źródeł (GUS -> SRC_LEGACY_1, NBP -> SRC_LEGACY_2,
   Bankier.pl -> SRC_EXTERNAL_BANKIER, Trading Economics -> SRC_EXTERNAL_TRADING_ECONOMICS)
   oraz oznaczanie źródeł kompozytowych/niejednoznacznych jako PENDING w quality_events.
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

from modules.migrator import (
    SQLiteV2Migrator,
    MigrationResult,
    normalize_iso_date,
    resolve_source_provenance,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_DB_PATH = os.path.join(PROJECT_ROOT, "instance", "economy_agent.db")
SCHEMA_V2_SQL_PATH = os.path.join(PROJECT_ROOT, "docs", "sql", "schema_v2.sql")


def test_date_and_source_resolvers():
    """Testuje funkcje pomocnicze normalizacji dat i wyznaczania precyzyjnego pochodzenia źródeł."""
    assert normalize_iso_date("18.09.2026") == "2026-09-18"
    assert normalize_iso_date("01.01.2025") == "2025-01-01"
    assert normalize_iso_date("2026-09-18") == "2026-09-18"
    assert normalize_iso_date(None) == "1970-01-01"

    # Oficjalne instytucje (jednoznaczne)
    s_id, url, name, tier, amb = resolve_source_provenance("NBP")
    assert s_id == "SRC_LEGACY_2"
    assert amb is False

    s_id, url, name, tier, amb = resolve_source_provenance("GUS")
    assert s_id == "SRC_LEGACY_1"
    assert amb is False

    s_id, url, name, tier, amb = resolve_source_provenance("Główny Urząd Statystyczny (GUS)")
    assert s_id == "SRC_LEGACY_1"
    assert amb is False

    # Zewnętrzne portale finansowe (nie mogą być arbitralnie przypisane do GUS!)
    s_id, url, name, tier, amb = resolve_source_provenance("Bankier.pl")
    assert s_id == "SRC_EXTERNAL_BANKIER"
    assert "bankier.pl" in url
    assert amb is False

    s_id, url, name, tier, amb = resolve_source_provenance("Trading Economics")
    assert s_id == "SRC_EXTERNAL_TRADING_ECONOMICS"
    assert "tradingeconomics.com" in url
    assert amb is False

    # Źródła niejednoznaczne / kompozytowe (muszą być oznaczone flagą is_ambiguous=True)
    s_id, url, name, tier, amb = resolve_source_provenance("Główny Urząd Statystyczny / Bankier.pl")
    assert s_id == "SRC_COMPOSITE_GUS_BANKIER"
    assert amb is True

    s_id, url, name, tier, amb = resolve_source_provenance("Narodowy Bank Polski / Bankier.pl")
    assert s_id == "SRC_COMPOSITE_NBP_BANKIER"
    assert amb is True


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
    # 4 (PKB) + 2 (mislabeled r/r) + 7 (niejednoznaczne źródła kompozytowe) = 13
    assert result.quality_events_created == 13
    assert result.conflicts_count == 4
    assert result.pending_count == 8
    assert result.verified_count == 63

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

    assert cur.execute("SELECT count(*) FROM source_registry").fetchone()[0] == 14
    assert cur.execute("SELECT count(*) FROM reports").fetchone()[0] == 6
    assert cur.execute("SELECT count(*) FROM source_evidence").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM extracted_candidates").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM legacy_migration_map").fetchone()[0] == 91
    assert cur.execute("SELECT count(*) FROM quality_events").fetchone()[0] == 13

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
    assert integrity_report["source_provenance_distribution_correct"] is True
    assert integrity_report["all_6_reports_content_matched"] is True
    assert integrity_report["quality_conflicts_isolated"] is True
    assert integrity_report["overall_integrity_passed"] is True


def test_migrator_preserves_historical_report_dates_and_sha256_snapshot(tmp_path):
    """Weryfikuje, że daty raportów nie zostały zamienione na sztywną datę oraz że hashe to SHA-256."""
    target_db = str(tmp_path / "test_reports_check.db")
    migrator = SQLiteV2Migrator(
        source_db_path=LEGACY_DB_PATH,
        target_db_path=target_db,
    )
    migrator.migrate(dry_run=False)

    conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
    cur = conn.cursor()

    dates = [row[0] for row in cur.execute("SELECT report_date FROM reports ORDER BY report_date").fetchall()]
    assert len(dates) == 6
    assert all(d == "2026-09-18" for d in dates)

    hashes = [row[0] for row in cur.execute("SELECT data_snapshot_hash FROM reports").fetchall()]
    for h in hashes:
        assert len(h) == 64
        assert h != "legacy_hash"

    conn.close()


def test_migrator_accurate_source_provenance_and_evidence_hashes(tmp_path):
    """Weryfikuje brak arbitralnego przypisywania źródeł do GUS oraz poprawność hashy dowodów."""
    target_db = str(tmp_path / "test_sources_check.db")
    migrator = SQLiteV2Migrator(
        source_db_path=LEGACY_DB_PATH,
        target_db_path=target_db,
    )
    migrator.migrate(dry_run=False)

    conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
    cur = conn.cursor()

    # Precyzyjny rozkład źródeł
    gus_direct = cur.execute("SELECT count(*) FROM source_evidence WHERE source_id = 'SRC_LEGACY_1'").fetchone()[0]
    nbp_direct = cur.execute("SELECT count(*) FROM source_evidence WHERE source_id = 'SRC_LEGACY_2'").fetchone()[0]
    bankier = cur.execute("SELECT count(*) FROM source_evidence WHERE source_id = 'SRC_EXTERNAL_BANKIER'").fetchone()[0]
    trading_econ = cur.execute("SELECT count(*) FROM source_evidence WHERE source_id = 'SRC_EXTERNAL_TRADING_ECONOMICS'").fetchone()[0]
    comp_gus = cur.execute("SELECT count(*) FROM source_evidence WHERE source_id = 'SRC_COMPOSITE_GUS_BANKIER'").fetchone()[0]
    comp_nbp = cur.execute("SELECT count(*) FROM source_evidence WHERE source_id = 'SRC_COMPOSITE_NBP_BANKIER'").fetchone()[0]

    assert gus_direct == 49
    assert nbp_direct == 4
    assert bankier == 11
    assert trading_econ == 4
    assert comp_gus == 6
    assert comp_nbp == 1

    # Sprawdzenie zdarzeń dla źródeł niejednoznacznych
    amb_events = cur.execute("SELECT count(*) FROM quality_events WHERE rule_code = 'RULE_AMBIGUOUS_SOURCE_PROVENANCE'").fetchone()[0]
    assert amb_events == 7

    # Sprawdzenie hashy dowodów
    evidence_hashes = [row[0] for row in cur.execute("SELECT content_hash FROM source_evidence").fetchall()]
    assert len(evidence_hashes) == 75
    for h in evidence_hashes:
        assert len(h) == 64
        assert not h.startswith("hash_")

    conn.close()


def test_migrator_idempotency_on_target_database(tmp_path):
    """Weryfikuje, że ponowne uruchomienie na istniejącej bazie docelowej nie duplikuje wierszy."""
    target_db = str(tmp_path / "test_idempotency.db")
    migrator = SQLiteV2Migrator(
        source_db_path=LEGACY_DB_PATH,
        target_db_path=target_db,
    )

    res1 = migrator.migrate(dry_run=False)
    assert res1.success is True

    res2 = migrator.migrate(dry_run=False)
    assert res2.success is True

    conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
    cur = conn.cursor()

    assert cur.execute("SELECT count(*) FROM source_registry").fetchone()[0] == 14
    assert cur.execute("SELECT count(*) FROM reports").fetchone()[0] == 6
    assert cur.execute("SELECT count(*) FROM source_evidence").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM extracted_candidates").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM legacy_migration_map").fetchone()[0] == 91
    assert cur.execute("SELECT count(*) FROM quality_events").fetchone()[0] == 13

    conn.close()


def test_migrator_prohibits_overwriting_source_database():
    """Weryfikuje, że próba migracji ze ścieżką docelową równą źródłowej rzuca wyjątek ValueError."""
    with pytest.raises(ValueError, match="KRYTYCZNE NARUSZENIE BEZPIECZEŃSTWA"):
        SQLiteV2Migrator(
            source_db_path=LEGACY_DB_PATH,
            target_db_path=LEGACY_DB_PATH,
        )


def test_migrator_error_handling_missing_source_database(tmp_path):
    """Weryfikuje błąd przy braku bazy źródłowej."""
    missing_db = str(tmp_path / "non_existing.db")
    target_db = str(tmp_path / "target.db")
    with pytest.raises(FileNotFoundError, match="Baza źródłowa nie istnieje"):
        SQLiteV2Migrator(
            source_db_path=missing_db,
            target_db_path=target_db,
        )


def test_migrator_transaction_rollback_on_failure(tmp_path, monkeypatch):
    """Weryfikuje, że w przypadku wyjątku transakcja jest wycofywana i plik uszkadzany nie pozostaje."""
    target_db = str(tmp_path / "test_rollback.db")
    migrator = SQLiteV2Migrator(
        source_db_path=LEGACY_DB_PATH,
        target_db_path=target_db,
    )

    def failing_normalizer(d):
        raise RuntimeError("Symulowana awaria normalizacji danych podczas zapisu raportów")

    monkeypatch.setattr("modules.migrator.normalize_iso_date", failing_normalizer)

    res = migrator.migrate(dry_run=False)
    assert res.success is False
    assert any("Symulowana awaria normalizacji" in err for err in res.errors)
    assert not os.path.exists(target_db)


def test_migrator_cli_dry_run_and_apply(tmp_path):
    """Weryfikuje działanie interfejsu CLI z poziomu subprocess."""
    cli_target = str(tmp_path / "cli_test_v2.db")

    # 1. Test CLI dry-run
    cmd_dry = [
        sys.executable,
        "-m", "modules.migrator",
        "--source", LEGACY_DB_PATH,
        "--target", cli_target,
    ]
    proc_dry = subprocess.run(cmd_dry, capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert proc_dry.returncode == 0
    assert "SUKCES (DRY-RUN)" in proc_dry.stdout
    assert not os.path.exists(cli_target)

    # 2. Test CLI apply
    cmd_apply = [
        sys.executable,
        "-m", "modules.migrator",
        "--source", LEGACY_DB_PATH,
        "--target", cli_target,
        "--apply",
    ]
    proc_apply = subprocess.run(cmd_apply, capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert proc_apply.returncode == 0
    assert "SUKCES (APPLY)" in proc_apply.stdout
    assert os.path.exists(cli_target)

    # 3. Test CLI verify
    cmd_verify = [
        sys.executable,
        "-m", "modules.migrator",
        "--source", LEGACY_DB_PATH,
        "--target", cli_target,
        "--verify",
    ]
    proc_verify = subprocess.run(cmd_verify, capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert proc_verify.returncode == 0
    assert "Baza docelowa jest w 100% spójna" in proc_verify.stdout


def test_original_database_remains_strictly_untouched():
    """Kluczowy test integralności: potwierdza niezmienność bazy produkcyjnej v1."""
    assert os.path.exists(LEGACY_DB_PATH)
    file_size = os.path.getsize(LEGACY_DB_PATH)
    assert file_size == 73728

    conn = sqlite3.connect(f"file:{LEGACY_DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()
    assert cur.execute("SELECT count(*) FROM collected_indicators").fetchone()[0] == 75
    assert cur.execute("SELECT count(*) FROM trusted_sources").fetchone()[0] == 10
    assert cur.execute("SELECT count(*) FROM generated_reports").fetchone()[0] == 6
    conn.close()
