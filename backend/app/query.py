from contextlib import contextmanager, nullcontext
from time import perf_counter

import psycopg
from psycopg.rows import tuple_row

from .catalog import read_catalog
from .database import Database
from .generation import TextToSQL
from .instrumentation import Trace
from .llm import LLMError, Message
from .models import PromptMessage, QueryResponse, QueryResult, QueryStage
from .validation import MAX_ROWS, SQLRejected, validate_sql

LLM_ERRORS = {
    "timeout": (504, "Tempo limite excedido durante a geração."),
    "unavailable": (503, "Modelo ou provedor indisponível."),
    "invalid_response": (502, "Resposta inválida durante a geração."),
}


class EmptyCatalog(Exception):
    pass


def classify(error: Exception) -> tuple[str, int, str]:
    if isinstance(error, EmptyCatalog):
        return "empty_catalog", 503, "Nenhuma tabela disponível para geração."
    if isinstance(error, LLMError):
        return error.kind, *LLM_ERRORS[error.kind]
    if isinstance(error, SQLRejected):
        return "sql_rejected", 422, str(error)
    if isinstance(error, psycopg.errors.QueryCanceled):
        return "database_timeout", 504, "Tempo limite excedido no PostgreSQL."
    if isinstance(error, psycopg.OperationalError):
        return "database_unavailable", 503, "PostgreSQL indisponível."
    if isinstance(error, psycopg.Error):
        return "database_error", 500, "Falha ao consultar o PostgreSQL."
    return "internal_error", 500, "Falha interna no processamento da consulta."


@contextmanager
def measure(stage: QueryStage, trace: Trace | None = None, **inputs):
    started = perf_counter()
    scope = trace.observe(stage.name, **inputs) if trace else nullcontext()
    try:
        with scope as observation:
            try:
                yield observation
            except Exception as error:
                if observation is not None:
                    observation.error = classify(error)[0]
                raise
    except Exception:
        stage.status = "failed"
        raise
    else:
        stage.status = "ok"
    finally:
        stage.duration_ms = round((perf_counter() - started) * 1000, 2)


def execute_query(database: Database, approved_sql: str) -> QueryResult:
    with database.connect() as connection, connection.cursor(row_factory=tuple_row) as cursor:
        cursor.execute(approved_sql)
        columns = [column.name for column in cursor.description]
        rows = cursor.fetchmany(MAX_ROWS + 1)
    return QueryResult(columns=columns, rows=rows[:MAX_ROWS], truncated=len(rows) > MAX_ROWS)


def run_query(
    database: Database, generator: TextToSQL, question: str, trace: Trace, *, execute: bool = True,
    include_prompt: bool = False,
) -> tuple[int, QueryResponse]:
    catalog_stage = QueryStage(name="catalog")
    generation_stage = QueryStage(name="generation")
    validation_stage = QueryStage(name="validation")
    execution_stage = QueryStage(name="execution")
    response = QueryResponse(
        request_id=trace.request_id,
        trace_id=trace.id,
        stages=[catalog_stage, generation_stage, validation_stage, execution_stage],
    )

    def capture_prompt(messages: list[Message]) -> None:
        response.prompt = [PromptMessage(**message) for message in messages]

    try:
        stage = catalog_stage
        with measure(stage, trace, dialect="postgresql") as observation:
            catalog = read_catalog(database)
            observation.output.update(
                table_count=len(catalog.tables), column_count=sum(len(table.columns) for table in catalog.tables)
            )
            if not catalog.tables:
                raise EmptyCatalog

        stage = generation_stage
        with measure(stage):
            response.generation = generator.generate(
                catalog.context, question, trace=trace,
                on_prompt=capture_prompt if include_prompt else None,
            )
        if not execute or response.generation.sql is None:
            return 200, response

        stage = validation_stage
        with measure(stage, trace, sql_chars=len(response.generation.sql)) as observation:
            approved_sql = validate_sql(response.generation.sql, catalog)
            observation.output["approved"] = True

        stage = execution_stage
        with measure(stage, trace, row_limit=MAX_ROWS) as observation:
            response.result = execute_query(database, approved_sql)
            observation.output.update(
                row_count=len(response.result.rows), truncated=response.result.truncated
            )
    except Exception as error:
        _, status, stage.detail = classify(error)
        return status, response
    return 200, response
