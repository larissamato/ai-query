"""Run the experimental suite through the same scientific API as the frontend."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import mkdtemp

import httpx

from app.config import get_settings
from evaluation.experimental import CASES, DATASET_SHA256


class InfrastructureError(Exception):
    pass


def select_cases(case_id, category, all_cases):
    if (case_id and category) or (all_cases and (case_id or category)):
        raise ValueError("Use um único filtro por caso ou categoria. benchmark-all percorre todo o catálogo.")
    if category:
        cases = [case for case in CASES.values() if case["category"].casefold() == category.strip().casefold()]
        if not cases:
            raise ValueError("Categoria experimental desconhecida.")
        return cases
    if all_cases:
        return list(CASES.values())
    if (case_id or "agg-01") not in CASES:
        raise ValueError("Identificador de pergunta experimental desconhecido.")
    return [CASES[case_id or "agg-01"]]


def request_json(client, method, url, service, **kwargs):
    try:
        response = client.request(method, url, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        return data
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status == 409:
            raise InfrastructureError(f"{service}: HTTP 409, snapshot incompatível. Execute make snapshot.") from None
        raise InfrastructureError(f"{service}: HTTP {status}. Confira a disponibilidade do serviço.") from None
    except (httpx.RequestError, ValueError):
        raise InfrastructureError(f"{service}: conexão interrompida, timeout ou resposta inválida.") from None


def select_models(client, settings, installed, requested, all_models):
    requested = list(dict.fromkeys(requested.split()))
    missing = set(requested).difference(installed["models"])
    if missing:
        raise InfrastructureError(f"Modelos não instalados no Ollama científico: {', '.join(sorted(missing))}.")
    if not all_models:
        if requested:
            return requested
        if installed["default"] in installed["models"]:
            return [installed["default"]]
        raise InfrastructureError("Modelo padrão ausente no Ollama científico. Execute make experiment-up.")

    selected = []
    for model in requested or installed["models"]:
        info = request_json(
            client, "POST", f"{str(settings.ollama_base_url).rstrip('/')}/api/show",
            "Ollama", json={"model": model}, timeout=10,
        )
        capabilities = info.get("capabilities")
        # Older Ollama versions omit capabilities. Use only explicitly configured tags in that case.
        supported = "completion" in capabilities if isinstance(capabilities, list) else (
            model in requested or model == installed["default"]
        )
        if supported and not info.get("remote_host") and not model.endswith(("-cloud", ":cloud")):
            selected.append(model)
        else:
            print(f"Modelo ignorado: {model} (geração local indisponível).", file=sys.stderr)
    if not selected:
        raise InfrastructureError("Nenhum modelo local compatível com geração de texto.")
    return selected


def run_attempt(client, case, model, repeat, snapshot):
    try:
        attempt = request_json(
            client, "POST", f"/api/evaluation/cases/{case['id']}/run", "API de avaliação",
            json={"model": model, "mode": "scientific"},
        )
        if attempt["snapshot_sha256"] != snapshot["snapshot_sha256"] or attempt["mode"] != "scientific":
            raise InfrastructureError("A API alterou o dataset ou o modo durante a rodada.")
        failed_stage = next((stage["name"] for stage in attempt["stages"] if stage["status"] == "failed"), None)
        outcome = attempt["outcome"]
        if failed_stage:
            failure = failed_stage
        elif outcome in {"result_mismatch", "operator_mismatch", "classification_mismatch"}:
            failure = "semantic_equivalence"
        elif outcome == "error":
            failure = "pipeline"
        else:
            failure = None
        return {**attempt, "case_id": case["id"], "repeat": repeat, "failure": failure}
    except (InfrastructureError, KeyError) as error:
        return {
            "case": case, "case_id": case["id"], "model_requested": model, "repeat": repeat,
            "outcome": "infrastructure_error", "failure": "infrastructure",
            "error_detail": str(error) if isinstance(error, InfrastructureError) else "Resposta da API incompleta.",
        }


def summarize(attempts):
    outcomes = dict(Counter(row["outcome"] for row in attempts))
    latencies = [row["latency_ms"] for row in attempts if row.get("latency_ms") is not None]
    summary = {
        "attempts": len(attempts), "outcomes": outcomes,
        "accuracy": outcomes.get("correct", 0) / len(attempts) if attempts else None,
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else None,
    }
    for kind in ("input_tokens", "output_tokens"):
        tokens = [row["usage"][kind] for row in attempts if (row.get("usage") or {}).get(kind) is not None]
        summary[kind] = sum(tokens) if tokens else None
    return summary


def export(directory, report):
    (directory / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    attempts = report["attempts"]
    fields = list(dict.fromkeys(["case_id", "model_requested", "repeat", "outcome", "failure", *(
        key for row in attempts for key in row
    )]))
    with (directory / "attempts.csv").open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in attempts:
            formatted = {}
            for key, value in row.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                elif isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                formatted[key] = value
            writer.writerow(formatted)


def run(args, cases, settings, client):
    started = datetime.now(timezone.utc)
    directory = Path(mkdtemp(prefix=started.strftime("%Y%m%dT%H%M%SZ-"), dir=args.output))
    report = {
        "started_at": started.isoformat(), "repeats": args.repeats, "case_ids": [case["id"] for case in cases],
        "attempts": [], "error": None,
    }
    attempts = report["attempts"]
    models = []
    try:
        snapshot = request_json(client, "GET", "/api/evaluation/snapshot", "Snapshot", timeout=15)
        report["dataset"] = snapshot
        if not snapshot["compatible"] or snapshot["reference_date"] != args.reference_date or (
            snapshot["dataset_sha256"] != DATASET_SHA256
        ):
            raise InfrastructureError("Snapshot ou catálogo incompatível. Confira make snapshot e make experiment-up.")
        installed = request_json(client, "GET", "/api/models", "Ollama", timeout=10)
        models = select_models(client, settings, installed, args.models, args.all)
        total = len(models) * args.repeats * len(cases)
        for model in models:
            for repeat in range(1, args.repeats + 1):
                for case in cases:
                    print(f"[{len(attempts) + 1}/{total}] {model} · {case['id']} · repetição {repeat}", file=sys.stderr)
                    attempt = run_attempt(client, case, model, repeat, snapshot)
                    attempts.append(attempt)
                    label = attempt["failure"] or attempt["outcome"]
                    print(f"  {attempt['outcome']} · {label} · trace {attempt.get('trace_id') or '—'}", file=sys.stderr)
                    if attempt["outcome"] == "infrastructure_error":
                        raise InfrastructureError(attempt["error_detail"])
    except (InfrastructureError, KeyError, KeyboardInterrupt) as error:
        if isinstance(error, InfrastructureError):
            report["error"] = str(error)
        elif isinstance(error, KeyboardInterrupt):
            report["error"] = "Rodada interrompida."
        else:
            report["error"] = "Resposta de infraestrutura incompleta."
        print(report["error"], file=sys.stderr)
    finally:
        report["summary"] = summarize(attempts)
        report["by_model"] = {
            model: summarize([row for row in attempts if row["model_requested"] == model]) for model in models
        }
        export(directory, report)
    print(f"Relatórios CSV e JSON gravados em {directory.name}.")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return int(bool(report["error"]) or any(row["outcome"] == "error" for row in attempts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--category", default="")
    parser.add_argument("--case", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-date", required=True)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--api", default="http://backend:8000")
    args = parser.parse_args()
    try:
        cases = select_cases(args.case, args.category, args.all)
        if args.repeats < 1:
            raise ValueError("--repeats deve ser maior que zero.")
    except ValueError as error:
        parser.error(str(error))
    settings = get_settings()
    with httpx.Client(base_url=args.api, timeout=settings.ollama_timeout_seconds + 30, trust_env=False) as client:
        raise SystemExit(run(args, cases, settings, client))


if __name__ == "__main__":
    main()
