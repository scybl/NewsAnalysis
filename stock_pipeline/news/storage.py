from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NewsDatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


class Mysql:
    def __init__(self, config: NewsDatabaseConfig):
        self._config = config
        self._db = None
        self.connect()

    def __enter__(self) -> "Mysql":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def connect(self) -> None:
        import pymysql

        self._db = pymysql.connect(
            host=self._config.host,
            port=self._config.port,
            user=self._config.user,
            passwd=self._config.password,
            db=self._config.database,
            charset="utf8mb4",
            autocommit=False,
        )

    def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None

    def execute(self, sql: str, args: tuple[Any, ...] | None = None) -> int:
        self.ping()
        cursor = self._db.cursor()
        try:
            cursor.execute(sql, args)
            self._db.commit()
            return cursor.rowcount
        except Exception:
            self._db.rollback()
            raise
        finally:
            cursor.close()

    def insert(self, sql: str, args: tuple[Any, ...] | None = None) -> int:
        return self.execute(sql, args)

    def query(self, sql: str, args: tuple[Any, ...] | None = None) -> tuple[Any, ...] | None:
        self.ping()
        cursor = self._db.cursor()
        try:
            cursor.execute(sql, args)
            return cursor.fetchone()
        finally:
            cursor.close()

    def queryall(self, sql: str, args: tuple[Any, ...] | None = None) -> tuple[tuple[Any, ...], ...]:
        self.ping()
        cursor = self._db.cursor()
        try:
            cursor.execute(sql, args)
            return cursor.fetchall()
        finally:
            cursor.close()

    def ping(self) -> None:
        try:
            self._db.ping(reconnect=True)
        except Exception:
            self.connect()


def ensure_schema(mysql: Mysql) -> None:
    columns = {row[0] for row in mysql.queryall("SHOW COLUMNS FROM news")}
    desired_columns = {
        "seq": "ALTER TABLE news ADD COLUMN seq varchar(32) DEFAULT NULL",
        "url": "ALTER TABLE news ADD COLUMN url varchar(255) DEFAULT NULL",
        "source": "ALTER TABLE news ADD COLUMN source varchar(128) DEFAULT NULL",
        "summary": "ALTER TABLE news ADD COLUMN summary text DEFAULT NULL",
        "created_at": "ALTER TABLE news ADD COLUMN created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    for column, sql in desired_columns.items():
        if column not in columns:
            mysql.execute(sql)

    indexes = {row[2] for row in mysql.queryall("SHOW INDEX FROM news")}
    if "uk_news_seq" not in indexes:
        mysql.execute("ALTER TABLE news ADD UNIQUE KEY uk_news_seq (seq)")
    if "idx_news_time" not in indexes:
        mysql.execute("ALTER TABLE news ADD KEY idx_news_time (time)")
    if "idx_news_type_time" not in indexes:
        mysql.execute("ALTER TABLE news ADD KEY idx_news_type_time (type(32), time)")


def initialize_database(config: NewsDatabaseConfig) -> None:
    import pymysql

    database = _quote_identifier(config.database)
    connection = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        passwd=config.password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
            cursor.execute(f"USE {database}")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS news (
                  id int(11) NOT NULL AUTO_INCREMENT,
                  seq varchar(32) DEFAULT NULL,
                  url varchar(255) DEFAULT NULL,
                  type text NOT NULL,
                  title text NOT NULL,
                  content text NOT NULL,
                  time datetime NOT NULL,
                  source varchar(128) DEFAULT NULL,
                  summary text DEFAULT NULL,
                  created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (id),
                  UNIQUE KEY uk_news_seq (seq),
                  KEY idx_news_time (time),
                  KEY idx_news_type_time (type(32), time)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        finally:
            cursor.close()
    finally:
        connection.close()


def _quote_identifier(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def is_existing(mysql: Mysql, info: dict[str, Any]) -> bool:
    if info.get("seq"):
        data = mysql.query("SELECT COUNT(*) FROM news WHERE seq = %s", (info.get("seq"),))
        return bool(data and data[0])
    if info.get("url"):
        data = mysql.query("SELECT COUNT(*) FROM news WHERE url = %s", (info.get("url"),))
        return bool(data and data[0])
    data = mysql.query("SELECT COUNT(*) FROM news WHERE title = %s", (info.get("title"),))
    return bool(data and data[0])


def insert_article(mysql: Mysql, info: dict[str, Any]) -> int:
    sql = """
        INSERT INTO news (seq, url, type, title, content, time, source, summary)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    return mysql.insert(
        sql,
        (
            info.get("seq"),
            info.get("url"),
            info.get("type"),
            info.get("title"),
            info.get("content"),
            info.get("time"),
            info.get("source"),
            info.get("summary"),
        ),
    )


def search_news(mysql: Mysql, terms: list[str], limit: int = 20, categories: list[str] | None = None) -> list[dict[str, Any]]:
    cleaned_terms = [term.strip() for term in terms if term and term.strip()]
    if not cleaned_terms:
        return []

    clauses = []
    params: list[Any] = []
    for term in cleaned_terms:
        pattern = f"%{term}%"
        clauses.append("(title LIKE %s OR summary LIKE %s OR content LIKE %s)")
        params.extend([pattern, pattern, pattern])

    category_clause = ""
    if categories:
        placeholders = ",".join(["%s"] * len(categories))
        category_clause = f" AND type IN ({placeholders})"
        params.extend(categories)

    safe_limit = max(1, min(int(limit), 200))
    rows = mysql.queryall(
        f"""
        SELECT seq, url, type, title, time, source, summary
        FROM news
        WHERE ({" OR ".join(clauses)}){category_clause}
        ORDER BY time DESC
        LIMIT {safe_limit}
        """,
        tuple(params),
    )
    return [_row_to_article(row) for row in rows]


def latest_news(mysql: Mysql, limit: int = 20, categories: list[str] | None = None) -> list[dict[str, Any]]:
    params: list[Any] = []
    category_clause = ""
    if categories:
        placeholders = ",".join(["%s"] * len(categories))
        category_clause = f"WHERE type IN ({placeholders})"
        params.extend(categories)
    safe_limit = max(1, min(int(limit), 200))
    rows = mysql.queryall(
        f"""
        SELECT seq, url, type, title, time, source, summary
        FROM news
        {category_clause}
        ORDER BY time DESC
        LIMIT {safe_limit}
        """,
        tuple(params),
    )
    return [_row_to_article(row) for row in rows]


def _row_to_article(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "seq": row[0],
        "url": row[1],
        "type": row[2],
        "title": row[3],
        "time": row[4].isoformat(sep=" ") if hasattr(row[4], "isoformat") else row[4],
        "source": row[5],
        "summary": row[6],
    }
