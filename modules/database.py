import datetime
import os
import sqlite3
from modules.sources import CountrySourcesResponse, EconomicSource


class EconomyDatabase:

  def __init__(self, db_name: str = "economy_agent.db"):
    instance_dir = "instance"
    os.makedirs(instance_dir, exist_ok=True)
    self.db_path = os.path.join(instance_dir, db_name)
    self.init_db()

  def init_db(self):
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS trusted_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT,
                country TEXT,
                name TEXT,
                url TEXT,
                description TEXT,
                created_at TIMESTAMP
            )
        """)
    cursor.execute("""
            CREATE TABLE IF NOT EXISTS collected_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT,
                country TEXT,
                indicator_name TEXT,
                value TEXT,
                period TEXT,
                source_name TEXT,
                page_info TEXT,
                created_at TIMESTAMP
            )
        """)
    conn.commit()
    conn.close()

  def are_indicators_fresh(self, country: str, max_days: int = 3) -> bool:
    """Sprawdza, czy w bazie istnieją dane od obu agentów nie starsze niż max_days."""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
            SELECT agent_name, MAX(created_at)
            FROM collected_indicators
            WHERE country = ?
            GROUP BY agent_name
        """,
        (country,),
    )
    rows = cursor.fetchall()
    conn.close()

    agents_found = {row[0]: row[1] for row in rows}

    # Wymagamy danych od obu agentów, by uznać zestaw za kompletny
    if (
        "GeminiAgent" not in agents_found
        or "GPTAgent" not in agents_found
    ):
      return False

    now = datetime.datetime.now()
    for agent, last_date_str in agents_found.items():
      try:
        last_date = datetime.datetime.fromisoformat(last_date_str)
        if (now - last_date).total_seconds() > (max_days * 86400):
          return False
      except (ValueError, TypeError):
        return False

    return True

  def get_sources(
      self, country: str, agent_name: str = "PolishEconomyAgent"
  ) -> CountrySourcesResponse | None:
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
            SELECT name, url, description FROM trusted_sources 
            WHERE country = ? AND agent_name = ?
        """,
        (country, agent_name),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
      return None

    sources_list = [
        EconomicSource(name=row[0], url=row[1], description=row[2])
        for row in rows
    ]
    return CountrySourcesResponse(country=country, sources=sources_list)

  def save_sources(
      self, data: CountrySourcesResponse, agent_name: str = "PolishEconomyAgent"
  ):
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    current_time = datetime.datetime.now().isoformat()

    cursor.execute(
        """
            DELETE FROM trusted_sources 
            WHERE country = ? AND agent_name = ?
        """,
        (data.country, agent_name),
    )

    for source in data.sources:
      cursor.execute(
          """
                INSERT INTO trusted_sources 
                (agent_name, country, name, url, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
          (
              agent_name,
              data.country,
              source.name,
              source.url,
              source.description,
              current_time,
          ),
      )

    conn.commit()
    conn.close()

  def save_indicators(self, agent_name: str, country: str, indicators: list):
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    current_time = datetime.datetime.now().isoformat()

    for ind in indicators:
      cursor.execute(
          """
                INSERT INTO collected_indicators 
                (agent_name, country, indicator_name, value, period, source_name, page_info, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
          (
              agent_name,
              country,
              ind.indicator_name,
              ind.value,
              ind.period,
              ind.source_name,
              ind.page_info,
              current_time,
          ),
      )

    conn.commit()
    conn.close()