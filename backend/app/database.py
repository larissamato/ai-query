from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import DictRow, dict_row

from .config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection[DictRow]]:
        with psycopg.connect(
            host=self.settings.ai_query_db_host,
            port=self.settings.ai_query_db_port,
            dbname="ai_query",
            user="ai_query_reader",
            password=self.settings.ai_query_password.get_secret_value(),
            connect_timeout=3,
            options="-c statement_timeout=3000 -c search_path=pg_catalog",
            row_factory=dict_row,
        ) as connection:
            connection.read_only = True
            connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            yield connection

    def check(self) -> None:
        with self.connect() as connection:
            connection.execute("SELECT 1")
