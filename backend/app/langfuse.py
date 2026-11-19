import json
import logging
import os
from queue import Empty, Full, Queue
from threading import Event, Thread

import httpx

from .instrumentation import Trace

logger = logging.getLogger(__name__)


def otlp_payload(trace: Trace) -> dict:
    root = trace.observations[0]
    spans = []
    for observation in trace.observations:
        attributes = {
            "langfuse.trace.name": trace.operation,
            "langfuse.environment": "local",
            "langfuse.observation.type": "generation" if observation.name == "generation" else "span",
            "langfuse.observation.input": json.dumps(observation.input),
            "langfuse.observation.output": json.dumps(observation.output),
            "langfuse.observation.metadata.status": "failed" if observation.error else "ok",
        }
        if observation.error:
            attributes["langfuse.observation.status_message"] = observation.error
        if observation.model:
            attributes["langfuse.observation.model.name"] = observation.model
        if observation.usage:
            attributes["langfuse.observation.usage_details"] = json.dumps(observation.usage)
        span = {
            "traceId": trace.id,
            "spanId": observation.span_id,
            "name": observation.name,
            "kind": 1,
            "startTimeUnixNano": str(observation.started_ns),
            "endTimeUnixNano": str(observation.ended_ns),
            "status": {"code": 2 if observation.error else 1},
            "attributes": [
                {"key": key, "value": {"stringValue": value}} for key, value in attributes.items()
            ],
        }
        if observation is not root:
            span["parentSpanId"] = root.span_id
        spans.append(span)

    return {"resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "ai-query-playground"}},
        ]},
        "scopeSpans": [{"scope": {"name": "ai-query"}, "spans": spans}],
    }]}


class LangfuseExporter:
    def __init__(self, url: str, public_key: str, secret_key: str):
        base = httpx.URL(url)
        if (
            base.scheme not in {"http", "https"} or not base.host
            or base.userinfo or base.query or base.fragment
        ):
            raise ValueError("URL base de telemetria inválida.")
        self.url = base.copy_with(path=f"{base.path.rstrip('/')}/api/public/otel/v1/traces")
        self.auth = httpx.BasicAuth(public_key, secret_key)
        self.pending: Queue[Trace] = Queue(maxsize=64)
        self.stopping = Event()
        self.thread = Thread(target=self.run, name="langfuse-export", daemon=True)
        self.thread.start()

    def submit(self, trace: Trace) -> None:
        try:
            self.pending.put_nowait(trace)
        except Full:
            logger.warning("Fila de telemetria cheia. Trace descartada.")

    def send(self, client: httpx.Client, trace: Trace) -> None:
        response = client.post(
            self.url,
            auth=self.auth,
            headers={"x-langfuse-ingestion-version": "4"},
            json=otlp_payload(trace),
        )
        response.raise_for_status()
        partial = response.json().get("partialSuccess", {})
        if int(partial.get("rejectedSpans", 0)):
            logger.warning("Langfuse rejeitou parte da trace.")

    def run(self) -> None:
        with httpx.Client(timeout=2, trust_env=False) as client:
            while not self.stopping.is_set():
                try:
                    trace = self.pending.get(timeout=0.2)
                except Empty:
                    continue
                try:
                    self.send(client, trace)
                except Exception:
                    logger.warning("Falha na exportação de telemetria para o Langfuse.")

    def close(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=2)


def configured_exporter() -> LangfuseExporter | None:
    url = os.getenv("LANGFUSE_BASE_URL", "")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    if url and public_key and secret_key:
        return LangfuseExporter(url, public_key, secret_key)
    return None
