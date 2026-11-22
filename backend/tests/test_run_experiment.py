import csv
import json
from types import SimpleNamespace

import httpx
import pytest

from evaluation.experimental import CASES, DATASET_SHA256
from evaluation.run_experiment import run, select_cases, select_models


def test_case_and_category_selection():
    assert len(select_cases("", "", True)) == 105
    assert select_cases("", "", False) == [CASES["agg-01"]]
    assert len(select_cases("", CASES["agg-01"]["category"], False)) == 7
    with pytest.raises(ValueError):
        select_cases("agg-01", CASES["agg-01"]["category"], False)


def test_all_models_only_selects_compatible_local_tags():
    capabilities = {
        "local": {"capabilities": ["completion"]},
        "embed": {"capabilities": ["embedding"]},
        "cloud": {"capabilities": ["completion"], "remote_host": "ollama.com"},
        "legacy-default": {},
        "legacy-unknown": {},
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, json=capabilities[json.loads(request.content)["model"]]
    ))
    with httpx.Client(transport=transport) as client:
        selected = select_models(
            client, SimpleNamespace(ollama_base_url="http://ollama"),
            {"models": list(capabilities), "default": "legacy-default"}, "", True,
        )
    assert selected == ["local", "legacy-default"]


def test_runner_preflights_and_exports_attempts_and_infrastructure_failure(tmp_path):
    requests = []

    def handle(request):
        requests.append(request.url.path)
        if request.url.path == "/api/evaluation/snapshot":
            return httpx.Response(200, json={
                "compatible": True, "reference_date": "2025-01-01",
                "snapshot_sha256": "frozen", "dataset_sha256": DATASET_SHA256,
            })
        if request.url.path == "/api/models":
            return httpx.Response(200, json={"models": ["local"], "default": "local"})
        assert json.loads(request.content) == {"model": "local", "mode": "scientific"}
        if requests.count(request.url.path) == 2:
            return httpx.Response(409)
        return httpx.Response(200, json={
            "mode": "scientific", "snapshot_sha256": "frozen", "stages": [],
            "outcome": "result_mismatch", "model_requested": "local", "trace_id": "trace",
            "latency_ms": 20, "usage": {"input_tokens": 12, "output_tokens": 8},
        })

    args = SimpleNamespace(
        repeats=3, output=tmp_path, reference_date="2025-01-01", models="", all=False,
    )
    with httpx.Client(base_url="http://backend", transport=httpx.MockTransport(handle)) as client:
        assert run(args, [CASES["agg-01"]], SimpleNamespace(), client) == 1
    [report_directory] = tmp_path.iterdir()
    report = json.loads((report_directory / "results.json").read_text())
    assert requests == ["/api/evaluation/snapshot", "/api/models", *["/api/evaluation/cases/agg-01/run"] * 2]
    assert report["summary"]["outcomes"] == {"result_mismatch": 1, "infrastructure_error": 1}
    assert report["by_model"]["local"]["input_tokens"] == 12
    assert "409" in report["error"]
    with (report_directory / "attempts.csv").open(encoding="utf-8-sig") as output:
        rows = list(csv.DictReader(output))
    assert [row["failure"] for row in rows] == ["semantic_equivalence", "infrastructure"]
    assert rows[0]["trace_id"] == "trace"
