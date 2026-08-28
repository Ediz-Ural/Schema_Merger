"""Provider-neutral LLM clients used only to produce analysis plans.

This module deliberately exposes text completion and text embedding only.  It
does not accept or transform table rows; callers should pass compact
schema/profile metadata, or — for entity resolution — the short comparison keys
of two records.

Embeddings are a separate interface (:class:`EmbeddingClient`) and a separate
provider setting (``EMBEDDING_PROVIDER``), so a project can score similarity
locally with Ollama while planning with a hosted model, or the other way round.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
from typing import Mapping, Sequence
from urllib import request

from dotenv import load_dotenv


class LLMConfigurationError(RuntimeError):
    """Raised when the selected provider has incomplete configuration."""


class LLMClient(ABC):
    """Common interface for a chat completion provider."""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Return one completion for the supplied instructions."""


class EmbeddingClient(ABC):
    """Common interface for a text embedding provider."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""


@dataclass(frozen=True)
class LLMConfig:
    """Configuration read from environment variables (or injected for tests)."""

    provider: str
    openai_api_key: str | None
    anthropic_api_key: str | None
    openai_model: str
    anthropic_model: str
    ollama_model: str
    ollama_base_url: str
    #: Provider used for embeddings; defaults to ``provider`` when unset.
    embedding_provider: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    ollama_embedding_model: str = "nomic-embed-text"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "LLMConfig":
        load_dotenv(override=False)
        values = os.environ if environment is None else environment
        provider = values.get("LLM_PROVIDER", "openai").strip().lower()
        return cls(
            provider=provider,
            openai_api_key=_nonempty(values.get("OPENAI_API_KEY")),
            anthropic_api_key=_nonempty(values.get("ANTHROPIC_API_KEY")),
            openai_model=values.get("OPENAI_MODEL", "gpt-5-nano"),
            anthropic_model=values.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
            ollama_model=values.get("OLLAMA_MODEL", "llama3.1"),
            ollama_base_url=values.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            embedding_provider=values.get("EMBEDDING_PROVIDER", provider).strip().lower(),
            openai_embedding_model=values.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            ollama_embedding_model=values.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
        )


def _nonempty(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


@dataclass
class FakeLLMClient(LLMClient):
    """In-memory client for tests; it never makes a network request."""

    response: str = ""
    calls: list[tuple[str, str]] | None = None
    responses: list[str] | None = None

    def complete(self, system: str, user: str) -> str:
        if self.calls is None:
            self.calls = []
        self.calls.append((system, user))
        if self.responses:
            return self.responses.pop(0)
        return self.response


@dataclass
class FakeEmbeddingClient(EmbeddingClient):
    """In-memory embedder for tests; it never makes a network request.

    ``vectors`` maps an exact input text to its vector.  Texts that are absent
    get ``default``, so a test only has to spell out the values it cares about.
    Every :meth:`embed` batch is recorded in ``calls``.
    """

    vectors: Mapping[str, Sequence[float]] = field(default_factory=dict)
    default: Sequence[float] = (0.0, 0.0, 1.0)
    calls: list[list[str]] = field(default_factory=list)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        self.calls.append(batch)
        return [[float(value) for value in self.vectors.get(text, self.default)] for text in batch]


@dataclass(frozen=True)
class OpenAIClient(LLMClient):
    api_key: str
    model: str

    def complete(self, system: str, user: str) -> str:
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover - depends on optional SDK
            raise LLMConfigurationError("OpenAI kullanmak için 'openai' paketi kurulmalı.") from error
        response = OpenAI(api_key=self.api_key).chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return response.choices[0].message.content or ""


@dataclass(frozen=True)
class AnthropicClient(LLMClient):
    api_key: str
    model: str

    def complete(self, system: str, user: str) -> str:
        try:
            from anthropic import Anthropic
        except ImportError as error:  # pragma: no cover - depends on optional SDK
            raise LLMConfigurationError("Anthropic kullanmak için 'anthropic' paketi kurulmalı.") from error
        response = Anthropic(api_key=self.api_key).messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


@dataclass(frozen=True)
class OllamaClient(LLMClient):
    model: str
    base_url: str
    timeout: float = 60.0

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
        ).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=self.timeout) as response:  # nosec B310 - configured local endpoint
            body = json.loads(response.read().decode("utf-8"))
        try:
            return body["message"]["content"]
        except (KeyError, TypeError) as error:
            raise RuntimeError("Ollama beklenen tamamlama yanıtını döndürmedi.") from error


@dataclass(frozen=True)
class OpenAIEmbeddingClient(EmbeddingClient):
    api_key: str
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        if not batch:
            return []
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover - depends on optional SDK
            raise LLMConfigurationError("OpenAI kullanmak için 'openai' paketi kurulmalı.") from error
        response = OpenAI(api_key=self.api_key).embeddings.create(model=self.model, input=batch)
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


@dataclass(frozen=True)
class OllamaEmbeddingClient(EmbeddingClient):
    """Local embeddings: the compared texts never leave the machine."""

    model: str
    base_url: str
    timeout: float = 60.0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        if not batch:
            return []
        payload = json.dumps({"model": self.model, "input": batch}).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=self.timeout) as response:  # nosec B310 - configured local endpoint
            body = json.loads(response.read().decode("utf-8"))
        vectors = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(batch):
            raise RuntimeError("Ollama beklenen embedding yanıtını döndürmedi.")
        return [[float(value) for value in vector] for vector in vectors]


def create_llm_client(
    config: LLMConfig | None = None, *, environment: Mapping[str, str] | None = None
) -> LLMClient:
    """Build the configured client without making a provider request."""

    selected = config or LLMConfig.from_environment(environment)
    if selected.provider == "openai":
        if not selected.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY tanımlı değil, .env dosyanı kontrol et.")
        return OpenAIClient(api_key=selected.openai_api_key, model=selected.openai_model)
    if selected.provider == "anthropic":
        if not selected.anthropic_api_key:
            raise LLMConfigurationError("ANTHROPIC_API_KEY tanımlı değil, .env dosyanı kontrol et.")
        return AnthropicClient(api_key=selected.anthropic_api_key, model=selected.anthropic_model)
    if selected.provider == "ollama":
        return OllamaClient(model=selected.ollama_model, base_url=selected.ollama_base_url)
    raise LLMConfigurationError(
        "LLM_PROVIDER geçersiz. 'openai', 'anthropic' veya 'ollama' kullanın."
    )


def create_embedding_client(
    config: LLMConfig | None = None, *, environment: Mapping[str, str] | None = None
) -> EmbeddingClient:
    """Build the configured embedder without making a provider request.

    ``EMBEDDING_PROVIDER`` selects the provider and falls back to
    ``LLM_PROVIDER``.  Anthropic ships no embedding endpoint, so that provider
    must be redirected explicitly rather than failing at request time.
    """

    selected = config or LLMConfig.from_environment(environment)
    provider = selected.embedding_provider or selected.provider
    if provider == "openai":
        if not selected.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY tanımlı değil, .env dosyanı kontrol et.")
        return OpenAIEmbeddingClient(
            api_key=selected.openai_api_key, model=selected.openai_embedding_model
        )
    if provider == "ollama":
        return OllamaEmbeddingClient(
            model=selected.ollama_embedding_model, base_url=selected.ollama_base_url
        )
    if provider == "anthropic":
        raise LLMConfigurationError(
            "Anthropic embedding sunmuyor. EMBEDDING_PROVIDER='openai' veya 'ollama' seçin."
        )
    raise LLMConfigurationError(
        "EMBEDDING_PROVIDER geçersiz. 'openai' veya 'ollama' kullanın."
    )
