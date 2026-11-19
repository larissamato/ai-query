import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from secrets import token_hex
from time import perf_counter_ns, time_ns
from typing import Literal, Protocol
from uuid import uuid4

logger = logging.getLogger(__name__)
Summary = dict[str, str | int | float | bool]


@dataclass(frozen=True)
class StageEvent:
    trace_id: str
    name: str
    status: Literal["running", "ok", "failed"]
    duration_ms: float | None = None
    error: str | None = None


class EventSink(Protocol):
    def __call__(self, event: StageEvent) -> None: ...


@dataclass
class Observation:
    name: str
    span_id: str
    started_ns: int
    input: Summary
    output: Summary = field(default_factory=dict)
    ended_ns: int = 0
    duration_ms: float = 0
    error: str | None = None
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class TraceSink(Protocol):
    def __call__(self, trace: "Trace") -> None: ...


class Trace:
    def __init__(self, operation: str, events: EventSink | None = None, export: TraceSink | None = None):
        request_uuid = uuid4()
        self.id = request_uuid.hex
        self.request_id = str(request_uuid)
        self.operation = operation
        self.events = events
        self.export = export
        self.observations: list[Observation] = []

    def emit(self, event: StageEvent) -> None:
        if self.events is not None:
            try:
                self.events(event)
            except Exception:
                logger.warning("Falha no consumidor de eventos da consulta.")

    @contextmanager
    def observe(self, name: str, **inputs: str | int | float | bool):
        observation = Observation(name, token_hex(8), time_ns(), inputs)
        self.observations.append(observation)
        started = perf_counter_ns()
        self.emit(StageEvent(self.id, name, "running"))
        try:
            yield observation
        except Exception:
            observation.error = observation.error or "internal_error"
            raise
        finally:
            elapsed = perf_counter_ns() - started
            observation.ended_ns = observation.started_ns + elapsed
            observation.duration_ms = round(elapsed / 1_000_000, 2)
            self.emit(StageEvent(
                self.id, name, "failed" if observation.error else "ok",
                observation.duration_ms, observation.error,
            ))
            if name == self.operation and self.export is not None:
                try:
                    self.export(self)
                except Exception:
                    logger.warning("Falha ao encaminhar a trace para exportação.")
