from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import date
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from app.catalog import read_catalog
from app.config import Settings, get_settings
from app.database import Database
from app.generation import TextToSQL
from app.llm import Completion, OllamaProvider
from app.main import app, get_database, get_generator
from app.models import GenerateResponse, QueryResponse, QueryResult, QueryStage
from app.validation import SQLRejected, validate_sql
from evaluation.experimental import CASES, dynamic_reference, frozen_references, load_reference, operator_present, same_rows
from evaluation.freeze_snapshot import capture, encode


def test_dataset_and_independent_expected_results():
    assert len(CASES) >= 100
    counts = Counter(case["category"] for case in CASES.values())
    assert len(counts) == 15 and min(counts.values()) >= 7
    for case in CASES.values():
        _, expected = load_reference(case["id"])
        assert (expected is not None) == (case["expected_status"] == "generated")
        assert bool(case["reference_sql"]) == (expected is not None)
        if expected is not None:
            assert not expected.truncated

    assert same_rows(load_reference("set-05")[1].rows, [[i] for i in range(1, 6)] + [[i] for i in range(3, 9)])
    assert same_rows(load_reference("prod-04")[1].rows, [[2], [5]])
    assert same_rows(load_reference("prod-05")[1].rows, [[1]])
    assert same_rows(load_reference("prod-06")[1].rows, [[2]])
    assert same_rows(load_reference("prod-07")[1].rows, [[i] for i in range(1, 11)])
    assert load_reference("null-07")[1].rows == [[False, True, None]]
    assert dict(load_reference("null-06")[1].rows) == {i: int(i == 2) for i in range(1, 11)}
    assert load_reference("quant-06")[1].rows == []


def test_multiset_comparison_with_tolerance_and_type_sensitivity():
    assert same_rows([[1.0000006], [1.0]], [[1.0], [1.0000015]])
    assert not same_rows([[1], [1]], [[1], [2]])
    assert not same_rows([[1]], [["1"]])
    assert not same_rows([[True]], [[1]])
    assert not same_rows([[None]], [[0]])
    assert not same_rows([[1], [2]], [[2], [1]], ordered=True)


def test_explicit_operator_checks():
    assert operator_present("SELECT 1 UNION ALL SELECT 2", "UnionAll")
    assert not operator_present("SELECT 1 UNION ALL SELECT 2", "Union")
    assert operator_present("SELECT 1 WHERE 1 > ALL(SELECT 0)", "All")
    assert not operator_present("SELECT 1 WHERE 1 > ALL(SELECT 0)", "Any")
    assert operator_present("SELECT * FROM ecommerce.products p JOIN ecommerce.products q ON p.price=q.price", "SELF")
    assert not operator_present("SELECT * FROM ecommerce.products p LEFT JOIN ecommerce.categories q ON p.category_id=q.category_id", "INNER")
    assert not operator_present("SELECT (SELECT COUNT(*) FROM ecommerce.products p)", "Correlated")
    assert operator_present(CASES["sub-03"]["reference_sql"], "InSubquery")
    assert not operator_present("SELECT (SELECT 1) WHERE 1 IN (1, 2)", "InSubquery")
    null_sql = CASES["null-01"]["reference_sql"]
    assert operator_present(null_sql, "LeftJoinIsNull")
    assert not operator_present(null_sql.replace("IS NULL", "IS NOT NULL"), "LeftJoinIsNull")
    assert not operator_present(null_sql.replace("LEFT JOIN", "INNER JOIN"), "LeftJoinIsNull")


@pytest.fixture
def snapshot_database():
    if os.getenv("AI_QUERY_TEST_EXPERIMENTAL") != "1":
        pytest.skip("Requer PostgreSQL com snapshot experimental")
    return Database(get_settings())


def test_frozen_references_against_postgresql(snapshot_database):
    captured = json.loads(json.dumps(capture(snapshot_database, date(2025, 1, 1), "ecommerce-v1"), default=encode))
    assert captured == json.loads(json.dumps(frozen_references(), default=encode))
    catalog = read_catalog(snapshot_database)
    assert not any(column.nullable for table in catalog.tables for column in table.columns)
    with pytest.raises(SQLRejected):
        validate_sql(CASES["set-01"]["reference_sql"], catalog)
    with pytest.raises(SQLRejected):
        validate_sql("SELECT 1 UNION SELECT 1 FROM information_schema.tables", catalog, experimental=True)
    with pytest.raises(SQLRejected):
        validate_sql("SELECT 1 WHERE 1 = ANY(SELECT 1 FROM information_schema.tables)", catalog, experimental=True)


def test_experimental_endpoint_grades_known_outputs(snapshot_database, monkeypatch):
    provider = OllamaProvider("http://ollama:11434", "simulado", 5)
    provider.model_digest = "test-model-digest"
    monkeypatch.setattr(provider, "complete", Mock())
    monkeypatch.setitem(app.dependency_overrides, get_generator, lambda: TextToSQL(provider))
    monkeypatch.setattr("app.main.select_generator", lambda generator, _: generator)
    with TestClient(app) as client:
        assert len(client.get("/api/evaluation/cases").json()["cases"]) == 105
        scenarios = [
            ("set-01", CASES["set-01"]["reference_sql"], "generated", "correct"),
            ("set-01", "SELECT product_id FROM ecommerce.products WHERE product_id<=12", "generated", "operator_mismatch"),
            ("set-01", "SELECT 1", "generated", "result_mismatch"),
            ("safe-01", None, "unanswerable", "correct"),
            ("safe-01", "SELECT 1", "generated", "classification_mismatch"),
            ("safe-01", "SELECT * FROM information_schema.tables", "generated", "sql_rejected"),
        ]
        for case_id, sql, status, outcome in scenarios:
            provider.complete.return_value = Completion(
                content=json.dumps(dict(status=status, sql=sql, explanation="Simulação", assumptions=[])),
                model="simulado", input_tokens=20, output_tokens=10,
            )
            response = client.post(f"/api/evaluation/cases/{case_id}/run", json={"model": "simulado", "mode": "scientific"})
            assert response.status_code == 200
            result = response.json()
            assert result["trace_id"] == response.headers["X-Trace-Id"]
            assert result["outcome"] == outcome
            assert result["mode"] == "scientific"
            assert result["reference_date"] == "2025-01-01"
            assert result["seed_version"] == "ecommerce-v1"
            assert result["model_digest"] == "test-model-digest"
            assert result["generation_config"]["options"]["seed"] == 42
            assert result["usage"] == {"input_tokens": 20, "output_tokens": 10}
            assert result["generation"]["sql"] == sql
            if outcome == "sql_rejected":
                assert result["result"] is None
                assert result["stages"][-1]["status"] == "skipped"

        provider.complete.reset_mock()
        monkeypatch.setattr("app.main.snapshot_digest", lambda _: "different")
        assert client.post("/api/evaluation/cases/set-01/run", json={"model": "simulado", "mode": "scientific"}).status_code == 409
        provider.complete.assert_not_called()


@pytest.mark.parametrize(("case_id", "rows", "truncated", "insufficient"), [
    ("agg-01", [[0]], False, False),
    ("set-01", [], False, True),
    ("set-01", [[1]], True, True),
    ("set-01", [[None]], False, True),
    ("quant-06", [], False, False),
    ("null-05", [[None]], False, False),
])
def test_dynamic_reference_coverage(case_id, rows, truncated, insufficient, monkeypatch):
    reader = object()
    result = QueryResult(columns=["value"], rows=rows, truncated=truncated)
    catalog_reader = Mock()
    validator = Mock(return_value="SELECT approved")
    executor = Mock(return_value=result)
    monkeypatch.setattr("evaluation.experimental.read_catalog", catalog_reader)
    monkeypatch.setattr("evaluation.experimental.validate_sql", validator)
    monkeypatch.setattr("evaluation.experimental.execute_query", executor)
    expected, reason = dynamic_reference(CASES[case_id], reader)
    assert expected is result and bool(reason) == insufficient
    catalog_reader.assert_called_once_with(reader)
    validator.assert_called_once_with(
        CASES[case_id]["reference_sql"], catalog_reader.return_value, experimental=True,
    )
    executor.assert_called_once_with(reader, "SELECT approved")


def test_dynamic_endpoint_uses_live_reference_and_reuses_transaction(monkeypatch, tmp_path):
    connection = object()

    @contextmanager
    def connect():
        yield connection

    settings = Settings(ai_query_password="test-reader", evaluation_snapshot_path=tmp_path / "manifest.json")
    database = SimpleNamespace(settings=settings, connect=connect)
    monkeypatch.setitem(app.dependency_overrides, get_database, lambda: database)
    monkeypatch.setitem(app.dependency_overrides, get_generator, lambda: TextToSQL(Mock()))
    monkeypatch.setattr("app.main.select_generator", lambda generator, _: generator)
    fingerprint = Mock(return_value="live-dataset")
    monkeypatch.setattr("app.main.snapshot_digest", fingerprint)
    live_result = QueryResult(columns=["count"], rows=[[42]], truncated=False)
    readers = []
    reason = None

    def reference(case, reader):
        readers.append(reader)
        return live_result, reason

    def candidate(reader, generator, question, trace, *, experimental):
        assert experimental and reader is readers.pop()
        with reader.connect() as shared:
            assert shared is connection
        return 200, QueryResponse(
            request_id=trace.request_id, trace_id=trace.id, stages=[QueryStage(name="validation", status="ok")],
            result=live_result, generation=GenerateResponse(
                status="generated", sql=CASES["agg-01"]["reference_sql"], explanation="Teste",
                assumptions=[], model="simulado", prompt_version="teste", latency_ms=0,
                request_id=trace.request_id, trace_id=trace.id, context="teste",
                input_tokens=None, output_tokens=None,
            ),
        )

    monkeypatch.setattr("app.main.dynamic_reference", reference)
    monkeypatch.setattr("app.main.run_query", candidate)
    with TestClient(app) as client:
        assert client.get("/api/evaluation/cases").json()["scientific"] is None
        run_url = "/api/evaluation/cases/agg-01/run"
        response = client.post(run_url, json={"model": "simulado"})
        assert response.status_code == 200
        result = response.json()
        assert result["outcome"] == "correct"
        assert result["expected_result"]["rows"] == [[42]]
        assert result["mode"] == "dynamic"
        assert result["snapshot_sha256"] == "live-dataset"
        assert result["seed_version"] is None
        fingerprint.assert_called_once_with(connection)
        assert client.post(run_url, json={"model": "simulado", "mode": "scientific"}).status_code == 503

        reason = "Referência sem cobertura."
        insufficient = client.post(run_url, json={"model": "simulado"}).json()
        assert insufficient["outcome"] == "insufficient_data"
        assert insufficient["insufficient_data_reason"] == "Referência sem cobertura."


def test_scientific_endpoint_uses_configured_manifest(monkeypatch, tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        **frozen_references(), "reference_date": "2026-02-01", "seed_version": "fixture-v2",
    }, default=encode))
    settings = Settings(ai_query_password="test-reader", evaluation_snapshot_path=path)
    database = SimpleNamespace(settings=settings, connect=lambda: nullcontext(object()))
    monkeypatch.setitem(app.dependency_overrides, get_database, lambda: database)
    monkeypatch.setitem(app.dependency_overrides, get_generator, lambda: TextToSQL(Mock()))
    selected = Mock()
    monkeypatch.setattr("app.main.select_generator", selected)
    monkeypatch.setattr("app.main.snapshot_digest", lambda _: "different")
    with TestClient(app) as client:
        scientific = client.get("/api/evaluation/cases").json()["scientific"]
        assert scientific["reference_date"] == "2026-02-01"
        assert scientific["seed_version"] == "fixture-v2"
        response = client.post("/api/evaluation/cases/agg-01/run", json={"model": "simulado", "mode": "scientific"})
        assert response.status_code == 409
        assert "2026-02-01" in response.json()["detail"]
        selected.assert_not_called()


def test_dynamic_endpoint_on_postgresql(monkeypatch, tmp_path):
    alternate_date = os.getenv("AI_QUERY_TEST_ALTERNATE_REFERENCE_DATE")
    if os.getenv("AI_QUERY_TEST_EXPERIMENTAL") != "1" and not alternate_date:
        pytest.skip("Requer PostgreSQL experimental")
    provider = Mock(model="simulado")
    monkeypatch.setitem(app.dependency_overrides, get_generator, lambda: TextToSQL(provider))
    monkeypatch.setattr("app.main.select_generator", lambda generator, _: generator)
    sql = CASES["agg-01"]["reference_sql"]
    provider.complete.return_value = Completion(
        content=json.dumps(dict(status="generated", sql=sql, explanation="Simulação", assumptions=[])),
        model="simulado",
    )
    with TestClient(app) as client:
        response = client.post("/api/evaluation/cases/agg-01/run", json={"model": "simulado"})
    assert response.status_code == 200
    result = response.json()
    assert result["outcome"] == "correct"
    assert result["expected_result"] == result["result"]
    assert len(result["snapshot_sha256"]) == 64
    if not alternate_date:
        return

    assert result["snapshot_sha256"] != frozen_references()["snapshot_sha256"]
    with TestClient(app) as client:
        url = "/api/evaluation/cases/agg-01/run"
        payload = {"model": "simulado", "mode": "scientific"}
        assert client.post(url, json=payload).status_code == 409

        settings = get_settings()
        manifest = capture(Database(settings), date.fromisoformat(alternate_date), "ecommerce-v1")
        path = tmp_path / "alternate-experimental-snapshot.json"
        path.write_text(json.dumps(manifest, default=encode))
        configured = Database(settings.model_copy(update={"evaluation_snapshot_path": path}))
        monkeypatch.setitem(app.dependency_overrides, get_database, lambda: configured)
        response = client.post(url, json=payload)
        assert response.status_code == 200
        controlled = response.json()
        assert controlled["mode"] == "scientific"
        assert controlled["outcome"] == "correct"
        assert controlled["reference_date"] == alternate_date
        assert controlled["snapshot_sha256"] == result["snapshot_sha256"]
