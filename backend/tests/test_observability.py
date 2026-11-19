import json
from threading import Event
from unittest.mock import Mock
from uuid import UUID

import anyio
import httpx
import pytest

from app.generation import TextToSQL
from app.instrumentation import Trace
from app.langfuse import LangfuseExporter, otlp_payload
from app.llm import Completion
from app.main import app, get_database, get_generator
from app.models import QueryResult, SchemaResponse, Table

QUESTION = "Pergunta sintética com marcador privado"
SQL = "SELECT 1 AS marcador_tambem_privado"
OBSERVATIONS = ["query", "catalog", "prompt", "generation", "validation", "execution", "response"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def pipeline(monkeypatch):
    catalog = SchemaResponse(
        schema_name="ecommerce", context="contexto_privado",
        tables=[Table(name="orders", columns=[], primary_key=[], foreign_keys=[])],
    )
    completion = Completion(
        json.dumps({"status": "generated", "sql": SQL, "explanation": "Explicação privada", "assumptions": []}),
        "modelo-simulado", 11, 7,
    )
    provider = Mock(model="modelo-simulado")
    provider.complete.return_value = completion
    exporter = Mock()
    monkeypatch.setattr(app.state, "exporter", exporter, raising=False)
    monkeypatch.setattr("app.query.read_catalog", Mock(return_value=catalog))
    monkeypatch.setattr(
        "app.query.execute_query",
        Mock(return_value=QueryResult(columns=["dado_privado"], rows=[["linha_privada"]], truncated=False)),
    )
    app.dependency_overrides[get_database] = lambda: Mock()
    app.dependency_overrides[get_generator] = lambda: TextToSQL(provider)
    yield provider, exporter
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_trace_is_correlated_and_contains_only_summaries(pipeline):
    _, exporter = pipeline
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query", json={"question": QUESTION})
        second = await client.post("/api/query/generate", json={"question": QUESTION})

    assert response.status_code == second.status_code == 200
    trace, = exporter.submit.call_args_list[0].args
    assert [item.name for item in trace.observations] == OBSERVATIONS
    assert response.headers["x-trace-id"] == response.json()["trace_id"] == trace.id
    assert UUID(hex=trace.id).version == 4
    assert response.json()["generation"]["trace_id"] == trace.id
    assert second.json()["trace_id"] != trace.id
    generation_trace, = exporter.submit.call_args_list[1].args
    assert [item.name for item in generation_trace.observations] == [
        "query.generate", "catalog", "prompt", "generation", "response",
    ]

    payload = otlp_payload(trace)
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert all(span["traceId"] == trace.id for span in spans)
    assert all(span["parentSpanId"] == spans[0]["spanId"] for span in spans[1:])
    assert all(int(span["endTimeUnixNano"]) >= int(span["startTimeUnixNano"]) for span in spans)
    generation = trace.observations[3]
    assert generation.model == "modelo-simulado"
    assert generation.usage == {"input": 11, "output": 7}
    assert trace.observations[5].output == {"row_count": 1, "truncated": False}
    for private in (QUESTION, SQL, "contexto_privado", "Explicação privada", "dado_privado", "linha_privada"):
        assert private not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.anyio
async def test_telemetry_failure_and_sql_rejection_preserve_response(pipeline, caplog):
    provider, exporter = pipeline
    provider.complete.return_value = Completion(
        json.dumps({
            "status": "generated", "sql": "SELECT 1 INTO resumo",
            "explanation": "teste", "assumptions": [],
        }),
        "modelo-simulado",
    )
    exporter.submit.side_effect = RuntimeError("credencial de exemplo que não pode aparecer")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/query/stream", json={"question": QUESTION})
    assert response.status_code == 200
    frames = [
        (frame.splitlines()[0].removeprefix("event: "), json.loads(frame.splitlines()[1][6:]))
        for frame in response.text.strip().split("\n\n")
    ]
    name, result = frames[-1]
    assert name == "result"
    assert result["http_status"] == 422
    assert result["response"]["trace_id"] == response.headers["x-trace-id"]
    assert any(data.get("error") == "sql_rejected" for _, data in frames)
    assert not any(data.get("name") == "execution" for _, data in frames)
    assert "credencial de exemplo" not in caplog.text


@pytest.mark.anyio
async def test_sse_reports_generation_start_before_model_returns(pipeline):
    provider, _ = pipeline
    model_may_finish = Event()
    completion = provider.complete.return_value

    def complete(*args):
        assert model_may_finish.wait(timeout=3)
        return completion

    provider.complete.side_effect = complete
    events = []

    async def receive():
        return {"type": "http.request", "body": json.dumps({"question": QUESTION}).encode(), "more_body": False}

    async def send(message):
        if message["type"] != "http.response.body" or not message.get("body"):
            return
        event = message["body"].decode()
        events.append(event)
        if '"name": "generation", "status": "running"' in event:
            model_may_finish.set()

    with anyio.fail_after(5):
        await app({
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "scheme": "http", "method": "POST", "path": "/api/query/stream",
            "query_string": b"", "headers": [(b"content-type", b"application/json")],
        }, receive, send)
    assert model_may_finish.is_set()
    assert events[-1].startswith('event: result\ndata: {"http_status":200')


def test_otlp_uses_v4_ingestion_endpoint():
    trace = Trace("query")
    with trace.observe("query", question_chars=8):
        pass

    def accept(request):
        assert request.url.path == "/api/public/otel/v1/traces"
        assert request.headers["x-langfuse-ingestion-version"] == "4"
        assert request.headers["authorization"].startswith("Basic ")
        assert json.loads(request.content) == otlp_payload(trace)
        return httpx.Response(200, json={})

    exporter = LangfuseExporter("http://langfuse:3000", "pk-test", "sk-test")
    try:
        with httpx.Client(transport=httpx.MockTransport(accept)) as client:
            exporter.send(client, trace)
    finally:
        exporter.close()
