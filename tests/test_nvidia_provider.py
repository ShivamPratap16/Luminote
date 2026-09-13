"""Tests for NVIDIA NIM AI provider integration.

These tests verify the NvidiaProvider in isolation without calling the live API.
A live integration test is included but skipped unless NVIDIA_API_KEY is set.
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch

from app.services.ai_provider import (
    NvidiaProvider,
    AIProviderError,
    AIProviderTimeout,
    AIProviderRateLimited,
    AIProviderInvalidResponse,
    _extract_json_from_response,
    create_ai_provider,
)


# ── JSON extraction tests ──────────────────────────────────────────


class TestExtractJsonFromResponse:
    """Test the shared JSON extraction logic that handles model quirks."""

    def test_clean_json(self):
        raw = '{"title": "Test", "overview": "Overview", "sections": []}'
        result = _extract_json_from_response(raw)
        assert result["title"] == "Test"

    def test_json_with_markdown_fence(self):
        raw = '```json\n{"title": "Test", "overview": "X", "sections": []}\n```'
        result = _extract_json_from_response(raw)
        assert result["title"] == "Test"

    def test_json_with_plain_fence(self):
        raw = '```\n{"title": "Test", "overview": "X", "sections": []}\n```'
        result = _extract_json_from_response(raw)
        assert result["title"] == "Test"

    def test_json_with_think_block(self):
        raw = '<think>Let me analyze this transcript...</think>\n{"title": "Test", "overview": "X", "sections": []}'
        result = _extract_json_from_response(raw)
        assert result["title"] == "Test"

    def test_json_with_think_and_fence(self):
        raw = '<think>reasoning here</think>\n```json\n{"title": "T", "overview": "O", "sections": []}\n```'
        result = _extract_json_from_response(raw)
        assert result["title"] == "T"

    def test_json_with_leading_text(self):
        raw = 'Here is the JSON output:\n{"title": "Test", "overview": "X", "sections": []}'
        result = _extract_json_from_response(raw)
        assert result["title"] == "Test"

    def test_empty_response_raises(self):
        with pytest.raises(AIProviderInvalidResponse):
            _extract_json_from_response("")

    def test_none_response_raises(self):
        with pytest.raises(AIProviderInvalidResponse):
            _extract_json_from_response(None)

    def test_invalid_json_raises(self):
        with pytest.raises(AIProviderInvalidResponse):
            _extract_json_from_response("this is not json at all")

    def test_truncated_json_raises(self):
        with pytest.raises(AIProviderInvalidResponse):
            _extract_json_from_response('{"title": "Test", "sections": [')


# ── NvidiaProvider unit tests ──────────────────────────────────────


class TestNvidiaProviderInit:
    """Test provider initialization and configuration."""

    @patch("app.services.ai_provider.settings.NVIDIA_API_KEY", None)
    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
            NvidiaProvider(api_key="", base_url="https://example.com", model="test")

    @patch("app.services.ai_provider.settings.NVIDIA_API_KEY", None)
    def test_none_api_key_raises(self):
        with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
            NvidiaProvider(api_key=None, base_url="https://example.com", model="test")

    def test_valid_init(self):
        provider = NvidiaProvider(
            api_key="test-key",
            base_url="https://integrate.api.nvidia.com/v1",
            model="openai/gpt-oss-20b",
        )
        assert provider.api_key == "test-key"
        assert provider.model == "openai/gpt-oss-20b"
        assert provider.base_url == "https://integrate.api.nvidia.com/v1"

class TestNvidiaProviderGeneration:
    """Test provider generation with mocked OpenAI client."""

    def _make_mock_response(self, content: str):
        """Create a mock OpenAI chat completion response."""
        mock_message = MagicMock()
        mock_message.content = content

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    def _sample_context(self):
        return {
            "lecture": {"title": "Test Lecture"},
            "chapters": [],
            "transcript": [
                {"start_seconds": 0, "end_seconds": 5, "text": "Hello world"},
            ],
        }

    @patch("openai.OpenAI")
    def test_successful_generation(self, mock_openai_cls):
        valid_json = json.dumps({
            "title": "Test Lecture",
            "overview": "A test overview.",
            "sections": [
                {
                    "title": "Section 1",
                    "summary": "Summary",
                    "key_points": ["point"],
                    "examples": [],
                    "important_terms": [],
                    "timestamps": [0.0],
                }
            ],
            "final_takeaways": ["takeaway"],
        })

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response(valid_json)
        mock_openai_cls.return_value = mock_client

        provider = NvidiaProvider(api_key="test-key", base_url="https://test.com", model="test-model")
        result = provider.generate_structured_notes(self._sample_context())

        assert result["title"] == "Test Lecture"
        assert len(result["sections"]) == 1

        # Verify the client was created with correct params
        mock_openai_cls.assert_called_once_with(
            api_key="test-key",
            base_url="https://test.com",
            timeout=120,
        )

        # Verify the API was called with correct model and stream=False
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["stream"] is False
        assert call_kwargs["temperature"] == 0.2

    @patch("openai.OpenAI")
    def test_timeout_raises_provider_timeout(self, mock_openai_cls):
        import openai
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APITimeoutError(request=MagicMock())
        mock_openai_cls.return_value = mock_client

        provider = NvidiaProvider(api_key="test-key", base_url="https://test.com", model="m")
        with pytest.raises(AIProviderTimeout):
            provider.generate_structured_notes(self._sample_context())

    @patch("openai.OpenAI")
    def test_rate_limit_raises_provider_rate_limited(self, mock_openai_cls):
        import openai
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.RateLimitError(
            message="rate limited", response=mock_response, body=None
        )
        mock_openai_cls.return_value = mock_client

        provider = NvidiaProvider(api_key="test-key", base_url="https://test.com", model="m")
        with pytest.raises(AIProviderRateLimited):
            provider.generate_structured_notes(self._sample_context())

    @patch("openai.OpenAI")
    def test_server_error_raises_provider_error(self, mock_openai_cls):
        import openai
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APIStatusError(
            message="internal error", response=mock_response, body=None
        )
        mock_openai_cls.return_value = mock_client

        provider = NvidiaProvider(api_key="test-key", base_url="https://test.com", model="m")
        with pytest.raises(AIProviderError):
            provider.generate_structured_notes(self._sample_context())

    @patch("openai.OpenAI")
    def test_connection_error_raises_provider_error(self, mock_openai_cls):
        import openai
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(request=MagicMock())
        mock_openai_cls.return_value = mock_client

        provider = NvidiaProvider(api_key="test-key", base_url="https://test.com", model="m")
        with pytest.raises(AIProviderError):
            provider.generate_structured_notes(self._sample_context())

    @patch("openai.OpenAI")
    def test_malformed_response_raises_invalid_response(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response("not json at all")
        mock_openai_cls.return_value = mock_client

        provider = NvidiaProvider(api_key="test-key", base_url="https://test.com", model="m")
        with pytest.raises(AIProviderInvalidResponse):
            provider.generate_structured_notes(self._sample_context())

    @patch("openai.OpenAI")
    def test_think_block_response_extracted(self, mock_openai_cls):
        """Verify that <think>...</think> blocks are stripped before JSON parsing."""
        json_body = json.dumps({
            "title": "Cleaned",
            "overview": "Overview",
            "sections": [{"title": "S", "summary": "S", "key_points": [], "examples": [], "important_terms": [], "timestamps": []}],
            "final_takeaways": [],
        })
        raw = f"<think>Let me reason about this...</think>\n{json_body}"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_mock_response(raw)
        mock_openai_cls.return_value = mock_client

        provider = NvidiaProvider(api_key="test-key", base_url="https://test.com", model="m")
        result = provider.generate_structured_notes(self._sample_context())
        assert result["title"] == "Cleaned"


# ── Factory test ───────────────────────────────────────────────────


class TestCreateAiProvider:
    @patch("app.services.ai_provider.settings.NVIDIA_API_KEY", "test-key")
    def test_factory_nvidia(self):
        """Verify factory creates NvidiaProvider when AI_PROVIDER=nvidia and key is set."""
        provider = create_ai_provider("nvidia")
        assert isinstance(provider, NvidiaProvider)

    def test_factory_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown AI provider"):
            create_ai_provider("unknown_provider")


# ── Live integration test (skipped without API key) ────────────────


@pytest.mark.skipif(
    not os.environ.get("NVIDIA_API_KEY"),
    reason="NVIDIA_API_KEY not set — skipping live integration test",
)
class TestNvidiaProviderLive:
    """Live test against real NVIDIA NIM API.

    Only runs when NVIDIA_API_KEY is present in the environment.
    """

    def test_live_generation(self):
        provider = NvidiaProvider(
            api_key=os.environ.get("NVIDIA_API_KEY", "dummy"),
            base_url="https://integrate.api.nvidia.com/v1",
            model="openai/gpt-oss-20b",
        )
        context = {
            "lecture": {"title": "Introduction to Testing"},
            "chapters": [],
            "transcript": [
                {"start_seconds": 0, "end_seconds": 10, "text": "Today we will discuss software testing."},
                {"start_seconds": 10, "end_seconds": 20, "text": "Unit tests verify individual functions."},
                {"start_seconds": 20, "end_seconds": 30, "text": "Integration tests verify system components."},
            ],
        }
        result = provider.generate_structured_notes(context)
        assert "title" in result
        assert "sections" in result
        assert isinstance(result["sections"], list)
