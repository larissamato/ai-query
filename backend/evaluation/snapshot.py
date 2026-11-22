"""Inspect and audit a versioned dataset using the PostgreSQL reader."""

import argparse
from datetime import date
import json
import os

import httpx
import psycopg

from app.config import get_settings
from app.database import Database
from evaluation.experimental import CASES, DATASET_SHA256, SnapshotDatabase, frozen_references, snapshot_digest
from evaluation.freeze_snapshot import capture, encode


def describe(database, *, verify_references=False):
    manifest = frozen_references(database.settings.evaluation_snapshot_path)
    counts = {}
    with database.connect() as connection:
        identity = connection.execute(
            "SELECT current_database() AS name, current_user AS role"
        ).fetchone()
        current = snapshot_digest(connection, counts=counts)
        expected = manifest["snapshot_sha256"]
        compatible = current == expected
        references_match = None
        if compatible and verify_references:
            captured = capture(
                SnapshotDatabase(database, connection), date.fromisoformat(manifest["reference_date"]),
                manifest["seed_version"],
            )
            references_match = json.loads(json.dumps(captured, default=encode)) == json.loads(
                json.dumps(manifest, default=encode)
            )
            compatible = references_match
    return {
        "database": identity["name"],
        "host": database.settings.ai_query_db_host,
        "port": database.settings.ai_query_db_port,
        "role": identity["role"],
        "dataset_sha256": DATASET_SHA256,
        "reference_date": manifest["reference_date"],
        "seed_version": manifest["seed_version"],
        "snapshot_sha256": current,
        "expected_snapshot_sha256": expected,
        "counts": counts,
        "questions": len(CASES),
        "compatible": compatible,
        "references_match": references_match,
    }


def check_services(status):
    with httpx.Client(timeout=10, trust_env=False) as client:
        gateway = client.get("http://frontend/api/evaluation/snapshot")
        gateway.raise_for_status()
        served = gateway.json()
        if not served["compatible"] or any(served[key] != status[key] for key in (
            "snapshot_sha256", "dataset_sha256", "reference_date",
        )):
            raise RuntimeError("O frontend serve uma API com outro dataset.")
        models = client.get("http://frontend/api/models")
        models.raise_for_status()
        if models.json()["default"] not in models.json()["models"]:
            raise RuntimeError("O modelo padrão não está instalado no Ollama científico.")
        print("Frontend, API e Ollama verificados.")

        base = os.environ.get("LANGFUSE_BASE_URL", "").rstrip("/")
        public = os.environ.get("LANGFUSE_PUBLIC_KEY")
        secret = os.environ.get("LANGFUSE_SECRET_KEY")
        if base:
            client.get(f"{base}/api/public/health?failIfDatabaseUnavailable=true").raise_for_status()
        if base and public and secret:
            response = client.get(f"{base}/api/public/projects", auth=(public, secret))
            response.raise_for_status()
            if not response.json().get("data"):
                raise RuntimeError("As chaves do Langfuse não retornaram um projeto.")
            print("Langfuse disponível e autenticação do projeto verificada.")
        else:
            print("Exportação ao Langfuse sem configuração completa.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-date", required=True)
    parser.add_argument("--verify-references", action="store_true")
    parser.add_argument("--check-services", action="store_true")
    args = parser.parse_args()
    try:
        status = describe(Database(get_settings()), verify_references=args.verify_references)
    except (OSError, ValueError, RuntimeError, AssertionError, psycopg.Error):
        parser.exit(1, "Falha ao ler o PostgreSQL ou auditar o manifesto. Confira o projeto, o schema e a conexão.\n")
    print(f"Banco: {status['database']} em {status['host']}:{status['port']} ({status['role']})")
    print(f"Referência: {status['reference_date']} · seed {status['seed_version']}")
    print(f"Identificador das perguntas: {status['dataset_sha256']} ({status['questions']} perguntas)")
    print(f"Hash atual:    {status['snapshot_sha256']}")
    print(f"Hash esperado: {status['expected_snapshot_sha256']}")
    for table, count in status["counts"].items():
        print(f"  {table}: {count}")
    if status["references_match"]:
        print("Resultados de referência reproduzidos.")
    if not status["compatible"] or status["reference_date"] != args.reference_date:
        parser.exit(
            1, "Status: incompatível. Confira REFERENCE_DATE e o manifesto versionado. "
            "Use o projeto científico correspondente ou prepare uma carga isolada compatível. "
            "Consulte docs/experimental-evaluation.md.\n",
        )
    print("Status: compatível.")
    if args.check_services:
        try:
            check_services(status)
        except (httpx.HTTPError, ValueError, KeyError, RuntimeError) as error:
            # Avoid including URLs or request credentials in diagnostics.
            label = str(error) if isinstance(error, RuntimeError) else "Confira o proxy, o Ollama e as chaves do Langfuse."
            parser.exit(1, f"Falha na verificação dos serviços. {label}\n")


if __name__ == "__main__":
    main()
