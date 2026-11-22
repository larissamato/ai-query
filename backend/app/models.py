from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["up"]


class ErrorResponse(BaseModel):
    detail: str


class Column(BaseModel):
    name: str
    data_type: str
    nullable: bool


class ForeignKey(BaseModel):
    name: str
    columns: list[str]
    referenced_schema: str
    referenced_table: str
    referenced_columns: list[str]


class Table(BaseModel):
    name: str
    columns: list[Column]
    primary_key: list[str]
    foreign_keys: list[ForeignKey]


class SchemaResponse(BaseModel):
    dialect: Literal["postgresql"] = "postgresql"
    schema_name: str
    tables: list[Table]
    context: str


class GenerateRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ModelQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["generated", "ambiguous", "unanswerable"]
    sql: NonBlankText | None
    explanation: NonBlankText
    assumptions: list[NonBlankText]

    @model_validator(mode="after")
    def check_sql_status(self):
        if (self.status == "generated") != (self.sql is not None):
            raise ValueError("SQL é obrigatório somente para o estado generated")
        return self


class GenerateResponse(ModelQuery):
    request_id: str
    trace_id: str
    context: str
    prompt_version: str
    model: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None


class QueryRequest(GenerateRequest):
    model_config = ConfigDict(extra="forbid")
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    include_prompt: bool = False


class ModelsResponse(BaseModel):
    models: list[str]
    default: str


class PromptMessage(BaseModel):
    role: Literal["system", "user"]
    content: str


class QueryStage(BaseModel):
    name: Literal["catalog", "generation", "validation", "execution"]
    status: Literal["ok", "failed", "skipped"] = "skipped"
    duration_ms: float | None = None
    detail: str | None = None


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


class QueryResponse(BaseModel):
    request_id: str
    trace_id: str
    stages: list[QueryStage]
    generation: GenerateResponse | None = None
    result: QueryResult | None = None
    prompt: list[PromptMessage] | None = None


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["dynamic", "scientific"] = "dynamic"
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
