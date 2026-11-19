import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from functools import partial
from typing import Annotated

import anyio
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from .catalog import read_catalog
from .config import get_settings
from .database import Database
from .generation import TextToSQL
from .instrumentation import EventSink, StageEvent, Trace
from .langfuse import configured_exporter
from .llm import LLMError, OllamaProvider
from .models import (
    ErrorResponse, GenerateRequest, GenerateResponse, HealthResponse, ModelsResponse, QueryRequest, QueryResponse,
    SchemaResponse,
)
from .query import run_query

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.exporter = configured_exporter()
    except Exception:
        logger.warning("Falha ao iniciar o exportador do Langfuse.")
        app.state.exporter = None
    try:
        yield
    finally:
        if app.state.exporter:
            await anyio.to_thread.run_sync(app.state.exporter.close)


app = FastAPI(title="AI Query Playground", lifespan=lifespan)
database_errors = {
    503: {"model": ErrorResponse, "description": "PostgreSQL indisponível ou configuração inválida"},
    500: {"model": ErrorResponse, "description": "Erro interno de acesso ao PostgreSQL"},
}


def get_database() -> Database:
    return Database(get_settings())


@app.exception_handler(psycopg.Error)
async def handle_database_error(_request: Request, error: psycopg.Error) -> JSONResponse:
    logger.warning("Falha no PostgreSQL (%s)", type(error).__name__)
    if isinstance(error, (psycopg.OperationalError, psycopg.errors.QueryCanceled)):
        return JSONResponse(status_code=503, content={"detail": "PostgreSQL indisponível."})
    return JSONResponse(status_code=500, content={"detail": "Falha ao consultar o PostgreSQL."})


@app.exception_handler(ValidationError)
async def handle_validation_error(_request: Request, error: ValidationError) -> JSONResponse:
    # Erros de validação podem conter entradas sensíveis.
    logger.error("Falha de validação interna (%s)", error.title)
    if error.title == "Settings":
        return JSONResponse(status_code=503, content={"detail": "Configuração do serviço inválida."})
    return JSONResponse(status_code=500, content={"detail": "Falha de validação interna."})


DatabaseDependency = Annotated[Database, Depends(get_database)]


@app.get("/health", responses=database_errors)
def health(database: DatabaseDependency) -> HealthResponse:
    database.check()
    return HealthResponse(status="ok", database="up")


@app.get("/api/schema", responses=database_errors)
def schema(database: DatabaseDependency) -> SchemaResponse:
    return read_catalog(database)


def ollama_provider(model: str | None = None) -> OllamaProvider:
    settings = get_settings()
    return OllamaProvider(
        base_url=str(settings.ollama_base_url),
        model=model or settings.ollama_model,
        timeout=settings.ollama_timeout_seconds,
    )


def available_models(provider: OllamaProvider) -> list[str]:
    try:
        return provider.list_models()
    except LLMError:
        raise HTTPException(503, "Lista de modelos do Ollama indisponível.") from None


@app.get("/api/models")
def models() -> ModelsResponse:
    provider = ollama_provider()
    return ModelsResponse(models=available_models(provider), default=provider.model)


def get_generator() -> TextToSQL:
    return TextToSQL(ollama_provider())


def select_generator(generator: TextToSQL, model: str | None) -> TextToSQL:
    if model is None:
        return generator
    provider = ollama_provider(model)
    if model not in available_models(provider):
        raise HTTPException(422, "O modelo selecionado não está instalado no Ollama.")
    return TextToSQL(provider)


GeneratorDependency = Annotated[TextToSQL, Depends(get_generator)]


def create_trace(http: Request, operation: str, events: EventSink | None = None) -> Trace:
    exporter = getattr(http.app.state, "exporter", None)
    return Trace(operation, events=events, export=exporter.submit if exporter else None)


def query_response(
    database: Database, generator: TextToSQL, question: str, trace: Trace, *, execute: bool = True,
    include_prompt: bool = False,
) -> JSONResponse:
    headers = {"X-Trace-Id": trace.id, "Cache-Control": "no-store"}
    with trace.observe(trace.operation, question_chars=len(question)) as root:
        status, response = run_query(
            database, generator, question, trace, execute=execute, include_prompt=include_prompt,
        )
        if not execute and status == 504 and response.stages[0].status == "failed":
            status = 503  # Preserve the generation endpoint's catalog error contract.
        if status >= 400:
            root.error = next(
                (item.error for item in reversed(trace.observations) if item.error), "query_failed"
            )

        with trace.observe("response", http_status=status) as observation:
            try:
                payload = response
                if not execute:
                    if status == 200:
                        payload = response.generation
                    else:
                        detail = next(stage.detail for stage in response.stages if stage.status == "failed")
                        payload = ErrorResponse(detail=detail)
                result = JSONResponse(
                    status_code=status, content=payload.model_dump(mode="json"), headers=headers
                )
            except (TypeError, ValueError):
                observation.error = "response_encoding_error"
                root.error = observation.error
                status = 500
                result = JSONResponse(
                    status_code=status,
                    content={"trace_id": trace.id, "detail": "Falha ao montar a resposta."},
                    headers=headers,
                )
            observation.output.update(http_status=status, response_bytes=len(result.body))
            root.output.update(http_status=status, has_result=response.result is not None)
            return result


@app.post(
    "/api/query/generate", response_model=GenerateResponse,
    responses={
        **database_errors,
        502: {"model": ErrorResponse, "description": "Resposta inválida do modelo"},
        503: {"model": ErrorResponse, "description": "Catálogo ou provedor indisponível"},
        504: {"model": ErrorResponse, "description": "Tempo limite durante a geração"},
    },
)
def generate_query(
    request: GenerateRequest, database: DatabaseDependency, generator: GeneratorDependency, http: Request
) -> JSONResponse:
    trace = create_trace(http, "query.generate")
    return query_response(database, generator, request.question, trace, execute=False)


@app.post(
    "/api/query", response_model=QueryResponse,
    responses={code: {"model": QueryResponse} for code in (422, 500, 502, 503, 504)},
)
def query(
    request: QueryRequest, database: DatabaseDependency, generator: GeneratorDependency, http: Request
) -> JSONResponse:
    generator = select_generator(generator, request.model)
    return query_response(
        database, generator, request.question, create_trace(http, "query"),
        include_prompt=request.include_prompt,
    )


@app.post("/api/query/stream", response_class=StreamingResponse, responses={
    200: {"content": {"text/event-stream": {}}},
})
async def stream_query(
    request: QueryRequest, database: DatabaseDependency, generator: GeneratorDependency, http: Request
) -> StreamingResponse:
    if request.model is not None:
        generator = await anyio.to_thread.run_sync(select_generator, generator, request.model)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[StageEvent | JSONResponse] = asyncio.Queue()
    trace = create_trace(http, "query", events=lambda event: loop.call_soon_threadsafe(queue.put_nowait, event))

    async def produce():
        try:
            process = partial(
                query_response, database, generator, request.question, trace,
                include_prompt=request.include_prompt,
            )
            result = await anyio.to_thread.run_sync(process, abandon_on_cancel=True)
        except Exception:
            logger.error("Falha interna ao processar a consulta em streaming.")
            result = JSONResponse(status_code=500, content={
                "trace_id": trace.id, "detail": "Falha interna no processamento da consulta.",
            })
        queue.put_nowait(result)

    async def events():
        producer = asyncio.create_task(produce())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if isinstance(event, JSONResponse):
                    body = event.body.decode("utf-8")
                    yield f'event: result\ndata: {{"http_status":{event.status_code},"response":{body}}}\n\n'
                    return
                yield f"event: stage\ndata: {json.dumps(asdict(event))}\n\n"
        finally:
            producer.cancel()

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no", "X-Trace-Id": trace.id},
    )
