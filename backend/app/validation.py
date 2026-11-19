from sqlglot import ErrorLevel, exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.errors import OptimizeError, ParseError, TokenError, UnsupportedError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.scope import Scope, traverse_scope

from .catalog import ALLOWED_TABLES, SCHEMA
from .models import SchemaResponse

MAX_ROWS = 100
MAX_SQL_LENGTH = 12_000

# Exact classes keep subclasses with different semantics outside the policy.
ALLOWED_NODES = {
    exp.Select, exp.Subquery, exp.With, exp.CTE, exp.Table, exp.TableAlias,
    exp.From, exp.Join, exp.Where, exp.Group, exp.Having, exp.Order, exp.Ordered,
    exp.Limit, exp.Offset, exp.Distinct, exp.Column, exp.Identifier, exp.Star,
    exp.Alias, exp.Literal, exp.Null, exp.Boolean, exp.Paren, exp.Tuple,
    exp.And, exp.Or, exp.Not, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
    exp.Is, exp.In, exp.Between, exp.Like, exp.ILike, exp.Exists,
    exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg,
    exp.Case, exp.If, exp.Interval, exp.Var, exp.DataType, exp.DataTypeParam,
    exp.Filter, exp.Window, exp.WindowSpec,
}

ALLOWED_FUNCTIONS = {
    exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Round, exp.Abs,
    exp.Coalesce, exp.Nullif, exp.Lower, exp.Upper, exp.Length, exp.Concat,
    exp.DateTrunc, exp.TimestampTrunc, exp.Extract, exp.CurrentDate,
    exp.CurrentTimestamp, exp.Cast, exp.RowNumber, exp.Rank, exp.DenseRank,
}

ALLOWED_TYPES = {
    exp.DataType.Type.BOOLEAN, exp.DataType.Type.SMALLINT, exp.DataType.Type.INT,
    exp.DataType.Type.BIGINT, exp.DataType.Type.DECIMAL, exp.DataType.Type.FLOAT,
    exp.DataType.Type.DOUBLE, exp.DataType.Type.TEXT, exp.DataType.Type.VARCHAR,
    exp.DataType.Type.DATE, exp.DataType.Type.TIMESTAMP, exp.DataType.Type.TIMESTAMPTZ,
}

INTERVAL_UNITS = {"YEAR", "MONTH", "WEEK", "DAY", "HOUR", "MINUTE", "SECOND", "QUARTER",
                  "DOW", "DOY", "ISODOW", "ISOYEAR", "EPOCH"}


class SQLRejected(Exception):
    pass


class ReadOnlyParser(Postgres.Parser):
    def _warn_unsupported(self) -> None:
        # The default command fallback logs a fragment of the raw candidate.
        raise SQLRejected("Comando SQL fora da lista permitida.")


def validate_sql(candidate: str, catalog: SchemaResponse) -> str:
    """Return only PostgreSQL rendered from the approved AST, with a row cap."""
    if len(candidate) > MAX_SQL_LENGTH:
        raise SQLRejected("O SQL excede o tamanho permitido.")

    try:
        dialect = Postgres()
        parser = ReadOnlyParser(dialect=dialect, error_level=ErrorLevel.RAISE)
        statements = parser.parse(dialect.tokenize(candidate), candidate)
        if len(statements) != 1 or type(statements[0]) is not exp.Select:
            raise SQLRejected("Apenas uma instrução SELECT é permitida.")

        query = normalize_identifiers(statements[0], dialect="postgres")
        for node in query.walk():
            if type(node) not in ALLOWED_NODES and type(node) not in ALLOWED_FUNCTIONS:
                raise SQLRejected("Construção SQL ou função fora da lista permitida.")
            if isinstance(node, exp.With) and node.args.get("recursive"):
                raise SQLRejected("CTEs recursivas não são permitidas.")
            if isinstance(node, exp.DataType) and node.this not in ALLOWED_TYPES:
                raise SQLRejected("Tipo SQL fora da lista permitida.")
            if isinstance(node, exp.Var) and (
                not isinstance(node.parent, (exp.Interval, exp.Extract, exp.DateTrunc, exp.TimestampTrunc))
                or node.name.upper() not in INTERVAL_UNITS
            ):
                raise SQLRejected("Unidade temporal fora da lista permitida.")
            if isinstance(node, exp.If) and not isinstance(node.parent, exp.Case):
                raise SQLRejected("Use CASE para expressões condicionais.")
            if isinstance(node, (exp.CTE, exp.Subquery)) and type(node.this) is not exp.Select:
                raise SQLRejected("CTEs e subconsultas devem conter SELECT.")

        visible = {table.name for table in catalog.tables}.intersection(ALLOWED_TABLES)
        checked = set()
        for scope in traverse_scope(query):
            for table in scope.tables:
                if (
                    type(table.this) is not exp.Identifier
                    or set(table.args) - {"this", "db", "catalog", "alias", "only"}
                    or table.catalog
                ):
                    raise SQLRejected("Fonte de dados fora da lista permitida.")
                source = scope.cte_sources.get(table.name)
                if table.db:
                    if table.db != SCHEMA or table.name not in visible:
                        raise SQLRejected("Tabela fora do catálogo autorizado.")
                    # Restrict reads to the catalog relation itself.
                    table.set("only", True)
                elif table.args.get("only") or not isinstance(source, Scope):
                    raise SQLRejected("Qualifique a tabela com o esquema autorizado.")
                checked.add(id(table))
        if any(id(table) not in checked for table in query.find_all(exp.Table)):
            raise SQLRejected("Fonte de dados fora de um escopo SELECT.")

        limit = MAX_ROWS + 1
        if query.args.get("limit"):
            value = query.args["limit"].expression
            if not isinstance(value, exp.Literal) or not value.is_int or len(value.this) > 18:
                raise SQLRejected("LIMIT deve ser um inteiro não negativo.")
            limit = min(limit, int(value.this))
        bounded = query.limit(limit, copy=False)
        return bounded.sql(dialect="postgres", comments=False, unsupported_level=ErrorLevel.RAISE)
    except (OptimizeError, ParseError, TokenError, UnsupportedError, RecursionError):
        raise SQLRejected("O SQL não pôde ser validado no dialeto PostgreSQL.") from None
