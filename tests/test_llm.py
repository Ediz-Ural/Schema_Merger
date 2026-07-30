import pytest

from core.llm import (
    AnthropicClient,
    FakeLLMClient,
    LLMConfigurationError,
    OllamaClient,
    OpenAIClient,
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
