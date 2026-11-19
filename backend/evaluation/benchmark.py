import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import httpx
import psycopg
from psycopg.rows import tuple_row

from app.config import get_settings
from app.database import Database
from app.generation import PROMPT_VERSION

BASE_URL = "http://127.0.0.1:8000"
CASES_PATH = Path(__file__).with_name("cases.json")
SEED_METADATA = """
SELECT count(*) AS orders, min(ordered_on)::text AS first_order,
       max(ordered_on)::text AS last_order
FROM ecommerce.orders
"""


def comparable(value):
    if type(value) in (int, float, Decimal, str):
        try:
            number = Decimal(str(value))
            if number.is_finite():
                return ("number", number)
        except InvalidOperation:
            pass
    return ("value", json.dumps(value, sort_keys=True, default=str))


def rows_match(expected, actual):
    def counted(rows):
        return Counter(tuple(comparable(value) for value in row) for row in rows)

    return counted(expected) == counted(actual)


def reference_results(cases, database):
    with database.connect() as connection:
        metadata = connection.execute(SEED_METADATA).fetchone()
        with connection.cursor(row_factory=tuple_row) as cursor:
            expected = {
                case["id"]: cursor.execute(case["reference_sql"]).fetchall()
                for case in cases if "reference_sql" in case
            }
    metadata["reference_digest"] = sha256(
        json.dumps(expected, sort_keys=True, default=str).encode()
    ).hexdigest()
    return metadata, expected


def run_case(client, case, model, repeat, reference):
    started = perf_counter()
    try:
        response = client.post("/api/query", json={"question": case["question"], "model": model})
        data = response.json()
        if not isinstance(data, dict):
            data = {}
        http_status = response.status_code
    except (httpx.HTTPError, ValueError):
        data, http_status = {}, None
    duration_ms = round((perf_counter() - started) * 1000, 2)
    generation = data.get("generation") or {}
    result = data.get("result") or {}
    failed = next((stage["name"] for stage in data.get("stages", []) if stage["status"] == "failed"), None)
    expected_status = case["expected_status"]
    actual_status = generation.get("status")
    if failed == "validation":
        outcome = "sql_rejected"
    elif http_status != 200 or not generation:
        outcome = "error"
    elif actual_status != expected_status:
        outcome = "classification_mismatch"
    elif expected_status != "generated":
        outcome = "correct"
    elif result and not result.get("truncated") and rows_match(reference, result["rows"]):
        outcome = "correct"
    else:
        outcome = "result_mismatch"
    return {
        "case": case["id"], "model_requested": model, "model_returned": generation.get("model"),
        "repeat": repeat, "outcome": outcome, "http_status": http_status, "failed_stage": failed,
        "expected_status": expected_status, "actual_status": actual_status, "latency_ms": duration_ms,
        "generation_latency_ms": generation.get("latency_ms"), "input_tokens": generation.get("input_tokens"),
        "output_tokens": generation.get("output_tokens"), "trace_id": data.get("trace_id"),
        "prompt_version": generation.get("prompt_version"),
    }


def main():
    parser = argparse.ArgumentParser(description="Avaliação da geração SQL na base sintética.")
    parser.add_argument("--models", default="", help="Tags instaladas, separadas por espaço")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats deve ser maior que zero")

    settings = get_settings()
    dataset = CASES_PATH.read_bytes()
    cases = json.loads(dataset)
    models = list(dict.fromkeys(args.models.split())) or [settings.ollama_model]
    try:
        with httpx.Client(
            base_url=BASE_URL, timeout=settings.ollama_timeout_seconds + 20, trust_env=False,
        ) as client:
            installed = client.get("/api/models", timeout=10)
            installed.raise_for_status()
            missing = set(models).difference(installed.json()["models"])
            if missing:
                parser.exit(1, "Instale os modelos solicitados no Ollama antes da avaliação.\n")

            metadata, expected = reference_results(cases, Database(settings))
            attempts = [
                run_case(client, case, model, repeat, expected.get(case["id"]))
                for model in models
                for repeat in range(1, args.repeats + 1)
                for case in cases
            ]
    except (httpx.HTTPError, psycopg.Error, ValueError, KeyError):
        parser.exit(1, "Falha ao consultar a API ou as referências da base sintética.\n")

    summary = {
        model: dict(Counter(attempt["outcome"] for attempt in attempts if attempt["model_requested"] == model))
        for model in models
    }
    print(json.dumps({
        "dataset_sha256": sha256(dataset).hexdigest(), "base": metadata,
        "prompt_version": PROMPT_VERSION, "repeats": args.repeats,
        "summary": summary, "attempts": attempts,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
