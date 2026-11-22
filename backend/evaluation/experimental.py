from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from psycopg.rows import tuple_row
from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import traverse_scope

from app.catalog import ALLOWED_TABLES, SCHEMA, read_catalog
from app.database import Database
from app.models import QueryResult
from app.query import execute_query
from app.validation import validate_sql

DIRECTORY = Path(__file__).parent
DATASET_BYTES = (DIRECTORY / "experimental_cases.json").read_bytes()
DATASET_SHA256 = sha256(DATASET_BYTES).hexdigest()
CASES = {case["id"]: case for case in json.loads(DATASET_BYTES)}
ABSOLUTE_TOLERANCE = Decimal("0.000001")
RELATIVE_TOLERANCE = Decimal("0.000000001")

PRIMARY_KEYS = {
    "customers": "customer_id", "categories": "category_id", "products": "product_id",
    "orders": "order_id", "order_items": "order_id, product_id",
}


def snapshot_digest(connection, *, counts=None):
    snapshot = {}
    with connection.cursor(row_factory=tuple_row) as cursor:
        for table in ALLOWED_TABLES:
            cursor.execute(f"SELECT * FROM ONLY {SCHEMA}.{table} ORDER BY {PRIMARY_KEYS[table]}")
            snapshot[table] = cursor.fetchall()
            if counts is not None:
                counts[table] = len(snapshot[table])
    return sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


class SnapshotDatabase(Database):
    """Reuse the verified repeatable-read transaction for catalog and candidate."""

    def __init__(self, database, connection):
        super().__init__(database.settings)
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


def numeric(value):
    # PostgreSQL NUMERIC remains a Decimal until the API encodes the results.
    if type(value) not in (int, float, Decimal):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def row_matches(left, right):
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        x, y = numeric(a), numeric(b)
        if x is not None and y is not None:
            if abs(x - y) > max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * max(abs(x), abs(y))):
                return False
        elif type(a) is not type(b) or a != b:
            return False
    return True


def same_rows(expected, actual, ordered=False):
    if len(expected) != len(actual):
        return False
    if ordered:
        return all(row_matches(a, b) for a, b in zip(expected, actual))

    # Find a one-to-one matching. Greedy pairing can fail when tolerances overlap.
    neighbors = [[j for j, row in enumerate(actual) if row_matches(value, row)] for value in expected]
    owners = {}

    def assign(index, seen):
        for candidate in neighbors[index]:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate not in owners or assign(owners[candidate], seen):
                owners[candidate] = index
                return True
        return False

    return all(assign(index, set()) for index in range(len(expected)))


def operator_present(sql, operator):
    tree = parse_one(sql, dialect="postgres")
    if operator == "LeftJoinIsNull":
        if not any(
            isinstance(node.expression, exp.Null) and not isinstance(node.parent, exp.Not)
            for node in tree.find_all(exp.Is)
        ):
            return False
        operator = "LEFT"
    if operator in {"INNER", "LEFT", "RIGHT", "FULL", "CROSS", "SELF"}:
        for select in tree.find_all(exp.Select):
            source = select.args.get("from_")
            if source is None:
                continue
            preceding = [source.this]
            for join in select.args.get("joins", []):
                if operator == "SELF":
                    if isinstance(join.this, exp.Table) and any(
                        isinstance(table, exp.Table)
                        and (table.db, table.name) == (join.this.db, join.this.name)
                        and table.alias_or_name != join.this.alias_or_name
                        for table in preceding
                    ):
                        return True
                else:
                    kind = join.side or join.kind or ("INNER" if join.args.get("on") or join.args.get("using") else "")
                    if kind == operator:
                        return True
                preceding.append(join.this)
        return False
    if operator in {"Union", "UnionAll", "Except", "Intersect"}:
        node_type = exp.Union if operator == "UnionAll" else getattr(exp, operator)
        return isinstance(tree, node_type) and tree.args.get("distinct", True) == (operator != "UnionAll")
    if operator == "Correlated":
        return any(scope.is_correlated_subquery for scope in traverse_scope(tree))
    if operator == "NotExists":
        return any(isinstance(node.this, exp.Exists) for node in tree.find_all(exp.Not))
    if operator == "InSubquery":
        return any(node.args.get("query") is not None for node in tree.find_all(exp.In))
    return tree.find(getattr(exp, operator)) is not None


def grade(case, expected, response, http_status):
    stages = {stage.name: stage for stage in response.stages}
    if stages["validation"].status == "failed":
        return "sql_rejected"
    if http_status != 200 or not response.generation:
        return "error"
    if response.generation.status != case["expected_status"]:
        return "classification_mismatch"
    if expected is None:
        return "correct"
    actual = response.result
    if actual is None or actual.truncated:
        return "result_mismatch"
    if len(expected.columns) != len(actual.columns) or (
        case.get("aliases") and expected.columns != actual.columns
    ) or not same_rows(expected.rows, actual.rows, case.get("ordered", False)):
        return "result_mismatch"
    if case.get("ordered") and not parse_one(response.generation.sql, dialect="postgres").args.get("order"):
        return "operator_mismatch"
    if case.get("operator") and not operator_present(response.generation.sql, case["operator"]):
        return "operator_mismatch"
    return "correct"


def dynamic_reference(case, reader):
    if case["reference_sql"] is None:
        return None, None
    catalog = read_catalog(reader)
    expected = execute_query(reader, validate_sql(case["reference_sql"], catalog, experimental=True))
    if expected.truncated:
        return expected, "A referência excede o limite de linhas da avaliação."
    if not expected.rows and case["id"] != "quant-06":
        return expected, "A consulta de referência não encontrou linhas para esta pergunta."
    if expected.rows and all(value is None for row in expected.rows for value in row) and case["id"] != "null-05":
        return expected, "A consulta de referência retornou apenas valores nulos."
    return expected, None


@lru_cache(maxsize=4)
def frozen_references(path=None):
    path = path or DIRECTORY / "experimental_snapshot.json"
    frozen = json.loads(path.read_text(), parse_float=Decimal)
    if (
        not isinstance(frozen, dict)
        or frozen.get("dataset_sha256") != DATASET_SHA256
        or not isinstance(frozen.get("reference_date"), str)
        or date.fromisoformat(frozen["reference_date"]).day != 1
        or not isinstance(frozen.get("seed_version"), str)
        or not frozen["seed_version"].strip()
        or not isinstance(frozen.get("snapshot_sha256"), str)
        or not isinstance(frozen.get("results"), dict)
        or set(frozen["results"]) != {key for key, case in CASES.items() if case["reference_sql"]}
    ):
        raise RuntimeError("As referências experimentais precisam ser verificadas novamente.")
    return frozen


def load_reference(case_id, path=None):
    frozen = frozen_references(path)
    expected = frozen["results"].get(case_id)
    return frozen["snapshot_sha256"], QueryResult.model_validate(expected) if expected is not None else None
