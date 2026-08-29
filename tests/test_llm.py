import pytest

from core.llm import (
    AnthropicClient,
    FakeEmbeddingClient,
    FakeLLMClient,
    LLMConfigurationError,
    OllamaClient,
    OllamaEmbeddingClient,
    OpenAIClient,
    OpenAIEmbeddingClient,
    create_embedding_client,
    create_llm_client,
)


@pytest.mark.parametrize(
    ("environment", "expected_type"),
    [
        ({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-key"}, OpenAIClient),
        ({"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"}, AnthropicClient),
        ({"LLM_PROVIDER": "ollama"}, OllamaClient),
    ],
)
def test_factory_selects_configured_provider(environment, expected_type):
    assert isinstance(create_llm_client(environment=environment), expected_type)


@pytest.mark.parametrize(
    ("environment", "variable"),
    [({"LLM_PROVIDER": "openai"}, "OPENAI_API_KEY"), ({"LLM_PROVIDER": "anthropic"}, "ANTHROPIC_API_KEY")],
)
def test_factory_has_clear_error_when_required_key_is_missing(environment, variable):
    with pytest.raises(LLMConfigurationError, match=variable):
        create_llm_client(environment=environment)


def test_fake_client_makes_no_network_call_and_records_prompt():
    client = FakeLLMClient(response="planned")

    assert client.complete("system prompt", "user prompt") == "planned"
    assert client.calls == [("system prompt", "user prompt")]


@pytest.mark.parametrize(
    ("environment", "expected_type"),
    [
        ({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-key"}, OpenAIEmbeddingClient),
        ({"LLM_PROVIDER": "ollama"}, OllamaEmbeddingClient),
        # The embedding provider can differ from the planning provider, so an
        # Anthropic plan can be paired with local, private similarity scoring.
        (
            {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k", "EMBEDDING_PROVIDER": "ollama"},
            OllamaEmbeddingClient,
        ),
    ],
)
def test_embedding_factory_selects_configured_provider(environment, expected_type):
    assert isinstance(create_embedding_client(environment=environment), expected_type)


def test_embedding_factory_reports_that_anthropic_has_no_embeddings():
    environment = {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"}

    with pytest.raises(LLMConfigurationError, match="EMBEDDING_PROVIDER"):
        create_embedding_client(environment=environment)


def test_embedding_factory_needs_the_openai_key():
    with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
        create_embedding_client(environment={"EMBEDDING_PROVIDER": "openai"})


def test_fake_embedder_makes_no_network_call_and_records_the_batch():
    embedder = FakeEmbeddingClient(vectors={"coca cola": [1.0, 0.0]}, default=[0.0, 1.0])

    assert embedder.embed(["coca cola", "fanta"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert embedder.calls == [["coca cola", "fanta"]]


def test_a_provider_that_refuses_the_call_raises_a_clean_request_error():
    """A reachable-but-refusing provider is a request failure, not a crash.

    Nothing on the network is contacted: the port is closed on purpose, which
    is the same transport failure an unreachable provider produces.
    """

    from core.llm import LLMRequestError, OllamaClient

    client = OllamaClient(model="phi3", base_url="http://127.0.0.1:1", timeout=2.0)

    with pytest.raises(LLMRequestError) as failure:
        client.complete("system", "user")

    message = str(failure.value)
    assert message.startswith("Ollama isteği başarısız:")
    assert "ağ bağlantısını kontrol et" in message.lower()


def test_a_missing_model_is_explained_with_what_to_do():
    from core.llm import LLMRequestError, _request_error

    error = _request_error(
        "OpenAI",
        "text-embedding-3-small",
        RuntimeError(
            "Error code: 403 - {'error': {'message': 'Project `proj_x` does not have access "
            "to model `text-embedding-3-small`', 'code': 'model_not_found'}}"
        ),
    )

    assert isinstance(error, LLMRequestError)
    assert "'text-embedding-3-small' modeline erişim yok" in str(error)


def test_an_invalid_key_is_named_without_echoing_the_key():
    from core.llm import _request_error

    error = _request_error("OpenAI", "gpt-5-nano", RuntimeError("Incorrect API key provided: sk-***"))

    assert "Anahtar geçersiz görünüyor" in str(error)
