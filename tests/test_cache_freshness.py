import datetime
import sqlite3
import pytest
from modules.database import EconomyDatabase


def test_cache_empty_database_returns_false(isolated_db):
    """Empty database must report indicators as not fresh."""
    assert isolated_db.are_indicators_fresh("Polska", max_days=3) is False


def test_cache_single_agent_returns_false(isolated_db, isolated_db_path):
    """When only GeminiAgent has data (GPTAgent missing), freshness must return False."""
    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    now_iso = datetime.datetime.now().isoformat()
    cur.execute("""
        INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info, created_at)
        VALUES ('GeminiAgent', 'Polska', 'PKB', '2026', '3.5%', 'GUS', 'http://gus.pl', ?)
    """, (now_iso,))
    conn.commit()
    conn.close()

    assert isolated_db.are_indicators_fresh("Polska", max_days=3) is False


def test_cache_both_agents_fresh_returns_true(isolated_db, isolated_db_path):
    """When both GeminiAgent and GPTAgent have entries within max_days, freshness must return True."""
    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    # 1 hour ago
    recent_time = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
    cur.execute("""
        INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info, created_at)
        VALUES ('GeminiAgent', 'Polska', 'PKB', '2026', '3.5%', 'GUS', 'http://gus.pl', ?)
    """, (recent_time,))
    cur.execute("""
        INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info, created_at)
        VALUES ('GPTAgent', 'Polska', 'CPI', '2026', '4.0%', 'GUS', 'http://gus.pl', ?)
    """, (recent_time,))
    conn.commit()
    conn.close()

    assert isolated_db.are_indicators_fresh("Polska", max_days=3) is True


def test_cache_stale_records_return_false(isolated_db, isolated_db_path):
    """When one agent's newest record is older than max_days, freshness must return False."""
    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    fresh_time = datetime.datetime.now().isoformat()
    stale_time = (datetime.datetime.now() - datetime.timedelta(days=4)).isoformat()

    cur.execute("""
        INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info, created_at)
        VALUES ('GeminiAgent', 'Polska', 'PKB', '2026', '3.5%', 'GUS', 'http://gus.pl', ?)
    """, (fresh_time,))
    cur.execute("""
        INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info, created_at)
        VALUES ('GPTAgent', 'Polska', 'CPI', '2026', '4.0%', 'GUS', 'http://gus.pl', ?)
    """, (stale_time,))
    conn.commit()
    conn.close()

    # With max_days=3, 4 days is stale
    assert isolated_db.are_indicators_fresh("Polska", max_days=3) is False


def test_cache_different_country_isolation(isolated_db, isolated_db_path):
    """Fresh data for Germany must not make Poland appear fresh."""
    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    now_iso = datetime.datetime.now().isoformat()
    for agent in ['GeminiAgent', 'GPTAgent']:
        cur.execute("""
            INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info, created_at)
            VALUES (?, 'Niemcy', 'DAX', '2026', '18000', 'Destatis', 'http://destatis.de', ?)
        """, (agent, now_iso))
    conn.commit()
    conn.close()

    assert isolated_db.are_indicators_fresh("Niemcy", max_days=3) is True
    assert isolated_db.are_indicators_fresh("Polska", max_days=3) is False


def test_cache_malformed_timestamp_handled_gracefully(isolated_db, isolated_db_path):
    """Corrupted ISO timestamps in created_at must safely evaluate to False instead of crashing."""
    conn = sqlite3.connect(isolated_db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info, created_at)
        VALUES ('GeminiAgent', 'Polska', 'PKB', '2026', '3.5%', 'GUS', 'http://gus.pl', 'NOT_AN_ISO_DATE')
    """)
    cur.execute("""
        INSERT INTO collected_indicators (agent_name, country, indicator_name, period, value, source_name, page_info, created_at)
        VALUES ('GPTAgent', 'Polska', 'CPI', '2026', '4.0%', 'GUS', 'http://gus.pl', '2026-09-18T12:00:00')
    """)
    conn.commit()
    conn.close()

    # Exception inside datetime.fromisoformat must be handled and return False
    assert isolated_db.are_indicators_fresh("Polska", max_days=3) is False
