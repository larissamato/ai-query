from contextlib import contextmanager
from unittest.mock import Mock

import httpx
import psycopg
import pytest
from pydantic import SecretStr

from app.catalog import ALLOWED_TABLES
from app.config import Settings, get_settings
from app.database import Database
from app.main import app, get_database


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_health_checks_database(client):
    database = Mock(spec=Database)
    app.dependency_overrides[get_database] = lambda: database
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}
    database.check.assert_called_once_with()


@pytest.mark.anyio
async def test_schema_returns_composite_keys_in_order(client):
    columns = [
        {"table_name": table, "name": column, "data_type": "integer", "nullable": False}
        for table, names in [
            ("order_items", ("order_id", "product_id")),
            ("orders", ("order_id", "customer_id")),
        ]
        for column in names
    ]
    keys = [
        {"table_name": "order_items", "kind": "p", "columns": ["order_id", "product_id"]},
        {
            "table_name": "order_items",
            "kind": "f",
            "name": "order_items_pair_fkey",
            "columns": ["product_id", "order_id"],
            "referenced_table": "orders",
            "referenced_columns": ["customer_id", "order_id"],
        },
    ]
    connection = Mock()
    connection.execute.side_effect = [Mock(fetchall=lambda: columns), Mock(fetchall=lambda: keys)]

    @contextmanager
    def connect():
        yield connection

    database = Mock(spec=Database, connect=connect)
    app.dependency_overrides[get_database] = lambda: database
    response = await client.get("/api/schema")
    assert response.status_code == 200
    catalog = response.json()
    assert catalog["dialect"] == "postgresql"
    assert catalog["schema_name"] == "ecommerce"
    items = catalog["tables"][0]
    assert items["primary_key"] == ["order_id", "product_id"]
    assert items["foreign_keys"][0]["columns"] == ["product_id", "order_id"]
    assert items["foreign_keys"][0]["referenced_columns"] == ["customer_id", "order_id"]
    assert "FK (product_id, order_id) -> ecommerce.orders (customer_id, order_id)" in catalog["context"]
    assert all(
        call.args[1] == ("ecommerce", list(ALLOWED_TABLES))
        for call in connection.execute.call_args_list
    )


@pytest.mark.parametrize("endpoint", ["/health", "/api/schema"])
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (psycopg.OperationalError, 503),
        (psycopg.errors.QueryCanceled, 503),
        (psycopg.ProgrammingError, 500),
    ],
)
@pytest.mark.anyio
async def test_database_errors_are_sanitized(client, monkeypatch, caplog, endpoint, error, expected_status):
    monkeypatch.setenv("AI_QUERY_PASSWORD", "test-secret")
    monkeypatch.setattr(psycopg, "connect", Mock(side_effect=error("test-secret")))
    response = await client.get(endpoint)
    assert response.status_code == expected_status
    assert "test-secret" not in response.text + caplog.text


@pytest.mark.anyio
async def test_missing_password_returns_503(client, monkeypatch):
    monkeypatch.delenv("AI_QUERY_PASSWORD", raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    response = await client.get("/health")
    assert response.status_code == 503


def test_connection_uses_fixed_reader_and_read_only_transaction(monkeypatch):
    connection = Mock()
    handle = Mock()
    handle.__enter__ = Mock(return_value=connection)
    handle.__exit__ = Mock(return_value=False)
    connect = Mock(return_value=handle)
    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setenv("PGUSER", "ai_query_admin")
    settings = Settings(ai_query_password=SecretStr("reader-secret"), _env_file=None)
    Database(settings).check()
    assert connect.call_args.kwargs["user"] == "ai_query_reader"
    assert connect.call_args.kwargs["password"] == "reader-secret"
    assert connection.read_only is True
    handle.__exit__.assert_called_once()
