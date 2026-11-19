from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

import httpx
from pydantic import BaseModel, Field, ValidationError


class Message(TypedDict):
    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True)
class Completion:
    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    truncated: bool = False


class LLMProvider(Protocol):
    model: str

    def complete(self, messages: list[Message], response_schema: dict) -> Completion: ...


class LLMError(Exception):
    def __init__(self, kind: Literal["timeout", "unavailable", "invalid_response"]) -> None:
        super().__init__(kind)
        self.kind = kind


class OllamaMessage(BaseModel):
    content: str


class OllamaResponse(BaseModel):
    model: str
    message: OllamaMessage
    done: Literal[True]
    done_reason: str | None = None
    prompt_eval_count: int | None = Field(default=None, ge=0)
    eval_count: int | None = Field(default=None, ge=0)


class OllamaModel(BaseModel):
    name: str


class OllamaModels(BaseModel):
    models: list[OllamaModel]


class OllamaProvider:
    def __init__(
        self, base_url: str, model: str, timeout: float, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = httpx.Timeout(timeout, connect=min(timeout, 5))
        self.transport = transport

    def list_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=5, transport=self.transport, trust_env=False) as client:
                response = client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            payload = OllamaModels.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError):
            raise LLMError("unavailable") from None
        return sorted({model.name for model in payload.models})

    def complete(self, messages: list[Message], response_schema: dict) -> Completion:
        try:
            with httpx.Client(
                timeout=self.timeout, transport=self.transport, trust_env=False
            ) as client:
                response = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "format": response_schema,
                        "stream": False,
                        "think": False,
                        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 512},
                    },
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            raise LLMError("timeout") from None
        except httpx.HTTPStatusError as error:
            kind = "unavailable" if error.response.status_code in (404, 503) else "invalid_response"
            raise LLMError(kind) from None
        except httpx.RequestError:
            raise LLMError("unavailable") from None

        try:
            payload = OllamaResponse.model_validate_json(response.content)
        except ValidationError:
            raise LLMError("invalid_response") from None
        return Completion(
            content=payload.message.content,
            model=payload.model,
            input_tokens=payload.prompt_eval_count,
            output_tokens=payload.eval_count,
            truncated=payload.done_reason == "length",
        )
