"""Print references from a freshly provisioned deterministic PostgreSQL fixture."""

from argparse import ArgumentParser
from datetime import date
from decimal import Decimal
import json

from app.catalog import read_catalog
from app.config import get_settings
from app.database import Database
from app.query import execute_query
from app.validation import validate_sql
from evaluation.experimental import (
    CASES, DATASET_SHA256, SnapshotDatabase, operator_present, same_rows, snapshot_digest,
)


def encode(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Unsupported reference value: {type(value).__name__}")


def capture(database, reference_date, seed_version):
    results = {}
    with database.connect() as connection:
        fingerprint = snapshot_digest(connection)
        reader = SnapshotDatabase(database, connection)
        catalog = read_catalog(reader)
        assert len(catalog.tables) == 5
        for case in CASES.values():
            sql = case["reference_sql"]
            if sql is None:
                assert case["expected_status"] != "generated"
                continue
            baseline = execute_query(reader, sql)
            approved = execute_query(reader, validate_sql(sql, catalog, experimental=True))
            assert not baseline.truncated and not approved.truncated, case["id"]
            assert baseline.columns == approved.columns, case["id"]
            assert same_rows(baseline.rows, approved.rows, case.get("ordered", False)), case["id"]
            assert not case.get("operator") or operator_present(sql, case["operator"]), case["id"]
            result = baseline.model_dump()
            if not case.get("ordered"):
                result["rows"].sort(key=lambda row: json.dumps(row, default=encode))
            results[case["id"]] = result
    return {
        "reference_date": reference_date.isoformat(), "seed_version": seed_version,
        "dataset_sha256": DATASET_SHA256, "snapshot_sha256": fingerprint, "results": results,
    }


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--reference-date", type=date.fromisoformat, required=True)
    parser.add_argument("--seed-version", required=True)
    args = parser.parse_args()
    if args.reference_date.day != 1 or not args.seed_version.strip():
        parser.error("Informe o primeiro dia do mês e uma versão de seed.")
    frozen = capture(Database(get_settings()), args.reference_date, args.seed_version)
    results = frozen.pop("results")
    metadata = [f"  {json.dumps(key)}: {json.dumps(value)}" for key, value in frozen.items()]
    lines = [
        f"    {json.dumps(key)}: {json.dumps(value, default=encode, ensure_ascii=False)}"
        for key, value in results.items()
    ]
    print("{\n" + ",\n".join(metadata) + ',\n  "results": {\n' + ",\n".join(lines) + "\n  }\n}")
