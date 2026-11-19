from .database import Database
from .models import Column, ForeignKey, SchemaResponse, Table

SCHEMA = "ecommerce"
ALLOWED_TABLES = ("customers", "categories", "products", "orders", "order_items")

# A lista de exposição da API e as concessões efetivas no banco se complementam.
VISIBLE_TABLES = """
WITH visible AS (
    SELECT c.oid, c.relname
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relname = ANY(%s::name[])
      AND c.relkind IN ('r', 'p')
      AND has_schema_privilege(n.oid, 'USAGE')
      AND has_table_privilege(c.oid, 'SELECT')
)
"""

COLUMNS_QUERY = VISIBLE_TABLES + """
SELECT t.relname AS table_name, a.attname AS name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       NOT a.attnotnull AS nullable
FROM visible AS t
LEFT JOIN pg_attribute AS a
    ON a.attrelid = t.oid AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY t.relname COLLATE "C", a.attnum
"""

KEYS_QUERY = VISIBLE_TABLES + """
SELECT source.relname AS table_name, k.contype AS kind, k.conname AS name,
       ARRAY(
           SELECT a.attname
           FROM unnest(k.conkey) WITH ORDINALITY AS key(attnum, position)
           JOIN pg_attribute AS a ON a.attrelid = k.conrelid AND a.attnum = key.attnum
           ORDER BY key.position
       ) AS columns,
       target.relname AS referenced_table,
       ARRAY(
           SELECT a.attname
           FROM unnest(k.confkey) WITH ORDINALITY AS key(attnum, position)
           JOIN pg_attribute AS a ON a.attrelid = k.confrelid AND a.attnum = key.attnum
           ORDER BY key.position
       ) AS referenced_columns
FROM pg_constraint AS k
JOIN visible AS source ON source.oid = k.conrelid
LEFT JOIN visible AS target ON target.oid = k.confrelid
WHERE k.contype = 'p' OR (k.contype = 'f' AND target.oid IS NOT NULL)
ORDER BY source.relname COLLATE "C", k.conname COLLATE "C"
"""


def read_catalog(database: Database) -> SchemaResponse:
    parameters = (SCHEMA, list(ALLOWED_TABLES))
    with database.connect() as connection:
        columns = connection.execute(COLUMNS_QUERY, parameters).fetchall()
        keys = connection.execute(KEYS_QUERY, parameters).fetchall()

    tables: dict[str, Table] = {}
    for row in columns:
        table_name = row["table_name"]
        if table_name not in tables:
            tables[table_name] = Table(name=table_name, columns=[], primary_key=[], foreign_keys=[])
        if row["name"] is not None:
            tables[table_name].columns.append(Column.model_validate(row))

    for key in keys:
        table = tables[key["table_name"]]
        if key["kind"] == "p":
            table.primary_key = key["columns"]
        else:
            table.foreign_keys.append(ForeignKey(referenced_schema=SCHEMA, **key))

    visible_tables = list(tables.values())
    return SchemaResponse(
        schema_name=SCHEMA, tables=visible_tables, context=format_context(visible_tables)
    )


def format_context(tables: list[Table]) -> str:
    lines = ["PostgreSQL"]
    for table in tables:
        columns = ", ".join(
            f"{column.name} {column.data_type}" + ("" if column.nullable else " NOT NULL")
            for column in table.columns
        )
        lines.append(f"{SCHEMA}.{table.name} ({columns})")
        if table.primary_key:
            lines.append(f"  PK ({', '.join(table.primary_key)})")
        for key in table.foreign_keys:
            lines.append(
                f"  FK ({', '.join(key.columns)}) -> {key.referenced_schema}."
                f"{key.referenced_table} ({', '.join(key.referenced_columns)})"
            )
    return "\n".join(lines)
