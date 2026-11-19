import json

import httpx
import pytest

from app.llm import OllamaProvider
from app.main import app, get_database, get_generator
from app.models import SchemaResponse, Table


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_models_and_prompt_use_the_real_ollama_contract(monkeypatch):
    sent = []
    schema = SchemaResponse(
        schema_name="ecommerce", context="ecommerce.orders (order_id integer)",
        tables=[Table(name="orders", columns=[], primary_key=[], foreign_keys=[])],
    )

    def ollama(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "padrao"}, {"name": "escolhido"}]})
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        sent.append(payload)
        return httpx.Response(200, json={
            "model": payload["model"], "done": True, "message": {"content": json.dumps({
                "status": "ambiguous", "sql": None, "explanation": "Qual métrica?", "assumptions": [],
            })},
        })

    def provider(model=None):
        return OllamaProvider("http://ollama:11434", model or "padrao", 10, httpx.MockTransport(ollama))

    monkeypatch.setattr("app.main.ollama_provider", provider)
    monkeypatch.setattr("app.query.read_catalog", lambda _database: schema)
    app.dependency_overrides[get_database] = lambda: object()

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            models = await client.get("/api/models")
            assert models.json() == {"models": ["escolhido", "padrao"], "default": "padrao"}

            rejected = await client.post("/api/query/stream", json={"question": "Qual métrica?", "model": "ausente"})
            assert rejected.status_code == 422
            assert not sent

            streamed = await client.post("/api/query/stream", json={
                "question": "Qual métrica?", "model": "escolhido", "include_prompt": True,
            })
            terminal = next(frame for frame in streamed.text.split("\n\n") if frame.startswith("event: result\n"))
            result = json.loads(terminal.split("\ndata: ", 1)[1])["response"]
            assert sent[0]["model"] == "escolhido"
            assert result["prompt"] == sent[0]["messages"]
            assert result["generation"]["status"] == "ambiguous"

            ordinary = await client.post("/api/query", json={"question": "Qual métrica?"})
            assert ordinary.status_code == 200
            assert ordinary.json()["prompt"] is None
            assert sent[1]["model"] == "padrao"
    finally:
        app.dependency_overrides.pop(get_database, None)
        app.dependency_overrides.pop(get_generator, None)
