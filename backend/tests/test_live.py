import os

import httpx
import pytest

BASE_URL = os.getenv("AI_QUERY_TEST_BASE_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="Defina AI_QUERY_TEST_BASE_URL para testar o Compose")


def test_live_catalog_and_health():
    with httpx.Client(base_url=BASE_URL) as client:
        health = client.get("/health")
        health.raise_for_status()
        assert health.json() == {"status": "ok", "database": "up"}
        response = client.get("/api/schema")
        response.raise_for_status()
        assert client.get("/docs").status_code == 200

    catalog = response.json()
    tables = {table["name"]: table for table in catalog["tables"]}
    assert set(tables) == {"customers", "categories", "products", "orders", "order_items"}
    assert tables["order_items"]["primary_key"] == ["order_id", "product_id"]
    assert {column["name"]: column["data_type"] for column in tables["products"]["columns"]}[
        "price"
    ] == "numeric(10,2)"
    assert {
        (table["name"], tuple(key["columns"]), key["referenced_schema"],
         key["referenced_table"], tuple(key["referenced_columns"]))
        for table in tables.values()
        for key in table["foreign_keys"]
    } == {
        ("products", ("category_id",), "ecommerce", "categories", ("category_id",)),
        ("orders", ("customer_id",), "ecommerce", "customers", ("customer_id",)),
        ("order_items", ("order_id",), "ecommerce", "orders", ("order_id",)),
        ("order_items", ("product_id",), "ecommerce", "products", ("product_id",)),
    }
    assert "FK (customer_id) -> ecommerce.customers (customer_id)" in catalog["context"]
