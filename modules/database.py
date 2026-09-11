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

  def get_indicator_chart_data(
      self, country: str, indicator_name: str
  ) -> dict:
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
            SELECT period, value, created_at 
            FROM collected_indicators 
            WHERE country = ? AND indicator_name = ?
            ORDER BY created_at ASC
        """,
        (country, indicator_name),
    )
    rows = cursor.fetchall()
    conn.close()

    labels = [row[0] for row in rows]
    data = []
    for row in rows:
      val_str = row[1].replace("%", "").replace(" pkt", "").strip()
      try:
        data.append(float(val_str))
      except ValueError:
        data.append(0.0)

    return {
        "labels": labels,
        "datasets": [{
            "label": indicator_name,
            "data": data,
            "fill": False,
            "borderColor": "rgb(75, 192, 192)",
            "tension": 0.1,
        }],
    }