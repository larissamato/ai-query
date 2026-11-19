import json
import logging
from unittest.mock import Mock

import httpx
import pytest

from app.generation import PROMPT_VERSION, TextToSQL
from app.llm import Completion, OllamaProvider
from app.main import app, get_database, get_generator
from app.models import SchemaResponse, Table

QUESTION = "Quantos pedidos foram registrados?"
CONTEXT = "PostgreSQL\necommerce.orders (order_id integer NOT NULL)"
SQL = "SELECT COUNT(*) FROM ecommerce.orders"
ANSWER = {
    "status": "generated",
    "sql": SQL,
    "explanation": "Conta as linhas da tabela de pedidos.",
    "assumptions": [],
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(monkeypatch):
    database = Mock()
    catalog = SchemaResponse(
        schema_name="ecommerce",
        tables=[Table(name="orders", columns=[], primary_key=[], foreign_keys=[])],
        context=CONTEXT,
    )
    read_catalog = Mock(return_value=catalog)
    monkeypatch.setattr("app.query.read_catalog", read_catalog)
    app.dependency_overrides[get_database] = lambda: database
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, database, read_catalog
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_ollama_generation_logs_metadata_without_executing_sql(client, caplog):
    api, database, read_catalog = client

    def ollama(request):
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "modelo-configurado"
        assert payload["stream"] is False
        assert payload["think"] is False
        assert set(payload["format"]["required"]) == {"status", "sql", "explanation", "assumptions"}
        assert CONTEXT in payload["messages"][0]["content"]
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1] == {"role": "user", "content": QUESTION}
        return httpx.Response(
            200,
            json={
                "model": "modelo-carregado",
                "message": {"content": json.dumps(ANSWER)},
                "done": True,
                "prompt_eval_count": 100,
                "eval_count": 25,
            },
        )

    provider = OllamaProvider("http://ollama:11434", "modelo-configurado", 10, httpx.MockTransport(ollama))
    app.dependency_overrides[get_generator] = lambda: TextToSQL(provider)
    with caplog.at_level(logging.INFO):
        response = await api.post("/api/query/generate", json={"question": QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert {key: body[key] for key in ANSWER} == ANSWER
    assert body["context"] == CONTEXT
    assert body["prompt_version"] == PROMPT_VERSION
    assert body["model"] == "modelo-carregado"
    assert body["input_tokens"] == 100
    assert body["output_tokens"] == 25
    assert body["latency_ms"] >= 0
    [record] = [r for r in caplog.records if r.getMessage().startswith("llm_generation ")]
    event = json.loads(record.getMessage().removeprefix("llm_generation "))
    assert event["request_id"] == body["request_id"]
    assert event["trace_id"] == body["trace_id"] == response.headers["x-trace-id"]
    assert event["input_tokens"] == 100
    assert event["output_tokens"] == 25
    assert QUESTION not in record.getMessage()
    assert SQL not in record.getMessage()
    read_catalog.assert_called_once_with(database)
    assert database.mock_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["ambiguous", "unanswerable"])
async def test_alternative_provider_returns_outcome_without_sql(client, caplog, status):
    api, _, _ = client
    content = json.dumps(dict(ANSWER, status=status, sql=None))
    provider = Mock(model="outro-modelo", **{"complete.return_value": Completion(content, "outro-modelo")})
    app.dependency_overrides[get_generator] = lambda: TextToSQL(provider)
    with caplog.at_level(logging.INFO):
        response = await api.post("/api/query/generate", json={"question": QUESTION})
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["sql"] is None
    assert response.json()["input_tokens"] is None
    assert QUESTION not in caplog.text
    assert "Conta as linhas" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario", "status"),
    [("timeout", 504), ("missing_model", 503), ("offline", 503), ("bad_json", 502),
     ("wrong_fields", 502), ("truncated", 502), ("invalid_status_sql", 502)],
)
async def test_generation_errors(client, scenario, status):
    api, _, _ = client

    def ollama(request):
        if scenario == "timeout":
            raise httpx.ReadTimeout("private upstream message", request=request)
        if scenario == "offline":
            raise httpx.ConnectError("private upstream message", request=request)
        if scenario == "missing_model":
            return httpx.Response(404, json={"error": "private upstream message"})
        if scenario == "wrong_fields":
            return httpx.Response(200, json={"unexpected": "private upstream message"})
        content = {
            "bad_json": "private upstream message",
            "invalid_status_sql": json.dumps(dict(ANSWER, status="ambiguous")),
        }.get(scenario, json.dumps(ANSWER))
        return httpx.Response(
            200,
            json={
                "model": "modelo",
                "message": {"content": content},
                "done": True,
                "done_reason": "length" if scenario == "truncated" else "stop",
            },
        )

    provider = OllamaProvider("http://ollama:11434", "modelo", 10, httpx.MockTransport(ollama))
    app.dependency_overrides[get_generator] = lambda: TextToSQL(provider)
    response = await api.post("/api/query/generate", json={"question": QUESTION})
    assert response.status_code == status
    assert "private upstream message" not in response.text


@pytest.mark.anyio
async def test_rejects_blank_question_before_catalog_access(client):
    api, _, read_catalog = client
    generator = Mock()
    app.dependency_overrides[get_generator] = lambda: generator
    response = await api.post("/api/query/generate", json={"question": "   "})
    assert response.status_code == 422
    read_catalog.assert_not_called()
    generator.generate.assert_not_called()
