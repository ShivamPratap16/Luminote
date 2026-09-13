"""AI provider abstraction layer.

Hides the specific model provider behind a stable interface so the rest
of the pipeline never imports openai/google SDK directly.
"""
import json
import re
import structlog
from abc import ABC, abstractmethod
from typing import Any, Dict
from app.core.config import settings

logger = structlog.get_logger(__name__)


class AIProviderError(Exception):
    """Base error for AI provider failures."""
    pass


class AIProviderTimeout(AIProviderError):
    """AI request timed out."""
    pass


class AIProviderRateLimited(AIProviderError):
    """AI provider rate limited the request."""
    pass


class AIProviderInvalidResponse(AIProviderError):
    """AI returned a response that is not valid JSON or doesn't match the schema."""
    pass


class AIProvider(ABC):
    """Abstract interface for AI providers.

    The pipeline calls generate_structured_notes() and gets back a dict.
    The dict is then validated against StructuredNotes schema externally.
    """

    @abstractmethod
    def generate_structured_notes(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Given assembled context (lecture, transcript, chapters), return structured notes dict.

        Must return a dict that can be validated against StructuredNotes schema.
        Raises AIProviderError on failure.
        """
        ...


def _build_system_prompt() -> str:
    """Shared system prompt for all providers."""
    return (
        "You are an expert study-notes generator. You receive lecture transcripts "
        "and produce structured JSON study notes.\n\n"
        "Output MUST be valid JSON matching this exact schema:\n"
        "{\n"
        '  "title": "string (lecture title)",\n'
        '  "overview": "string (2-3 sentence overview)",\n'
        '  "sections": [\n'
        "    {\n"
        '      "title": "string (section title)",\n'
        '      "summary": "string (section summary)",\n'
        '      "key_points": ["string", ...],\n'
        '      "examples": ["string", ...],\n'
        '      "important_terms": ["string", ...],\n'
        '      "timestamps": [float, ...]\n'
        "    }\n"
        "  ],\n"
        '  "final_takeaways": ["string", ...]\n'
        "}\n\n"
        "Rules:\n"
        "- Organize content into logical sections.\n"
        "- Preserve timestamps from the transcript where they appear in your notes.\n"
        "- Include specific examples from the lecture.\n"
        "- Identify important terms and definitions.\n"
        "- Keep summaries concise but informative.\n"
        "- Do NOT invent information not present in the transcript.\n"
        "- Output ONLY the JSON object. No markdown, no explanation, no code fences.\n"
    )


def _build_user_prompt(context: Dict[str, Any]) -> str:
    """Shared user prompt builder for all providers."""
    lecture = context.get("lecture", {})
    chapters = context.get("chapters", [])
    transcript = context.get("transcript", [])
    visual_events = context.get("visual_events", [])

    parts = [f"Lecture: {lecture.get('title', 'Unknown')}\n"]

    if chapters:
        parts.append("Chapters:")
        for ch in chapters:
            parts.append(
                f"  - {ch['title']} ({ch['start_seconds']:.0f}s - {ch['end_seconds']:.0f}s)"
            )
        parts.append("")

    if visual_events:
        parts.append("Visual Events on Screen (Slides/Whiteboard Context):")
        for ve in visual_events:
            parts.append(f"{ve['context']}")
        parts.append("")

    parts.append("Transcript:")
    for seg in transcript:
        ts = f"[{seg['start_seconds']:.1f}s]"
        parts.append(f"{ts} {seg['text']}")

    return "\n".join(parts)


def _extract_json_from_response(raw: str) -> Dict[str, Any]:
    """Extract and parse JSON from an AI response.

    Handles cases where models wrap JSON in markdown code fences,
    or include thinking/reasoning blocks before the JSON.
    Raises AIProviderInvalidResponse on failure.
    """
    if not raw or not raw.strip():
        raise AIProviderInvalidResponse("AI response is empty")

    text = raw.strip()

    # Strip <think>...</think> blocks (some models like Qwen emit these)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Strip markdown code fences: ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try to find a JSON object in the remaining text
    # Look for the first { and last } to handle trailing text
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        text = text[brace_start:brace_end + 1]

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise AIProviderInvalidResponse(f"AI response is not valid JSON: {e}")


# ── NVIDIA NIM Provider ────────────────────────────────────────────


class NvidiaProvider(AIProvider):
    """NVIDIA NIM AI provider using the OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or settings.NVIDIA_API_KEY
        self.base_url = base_url or settings.NVIDIA_BASE_URL
        self.model = model or settings.NVIDIA_TEXT_MODEL
        self.timeout = timeout or settings.AI_REQUEST_TIMEOUT

        if not self.api_key:
            raise ValueError(
                "NVIDIA_API_KEY is required for NVIDIA provider. "
                "Set it in .env or as an environment variable."
            )

    def generate_structured_notes(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate structured notes using NVIDIA NIM chat completion."""
        import openai

        client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
        )

        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(context)

        logger.info("Requesting notes from NVIDIA NIM", model=self.model)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=4096,
                stream=False,
            )
            raw_content = response.choices[0].message.content
            return _extract_json_from_response(raw_content)

        except openai.APITimeoutError as e:
            raise AIProviderTimeout(f"NVIDIA NIM request timed out: {e}")
        except openai.RateLimitError as e:
            raise AIProviderRateLimited(f"NVIDIA NIM rate limited: {e}")
        except openai.APIStatusError as e:
            raise AIProviderError(f"NVIDIA NIM API error (HTTP {e.status_code}): {e.message}")
        except openai.APIConnectionError as e:
            raise AIProviderError(f"NVIDIA NIM connection error: {e}")


# ── OpenAI Provider (legacy/alternative) ───────────────────────────


class OpenAIProvider(AIProvider):
    """OpenAI-based AI provider (GPT-4o, etc.)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_MODEL
        self.timeout = timeout or settings.AI_REQUEST_TIMEOUT

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")

    def generate_structured_notes(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate structured notes using OpenAI chat completion."""
        import openai

        client = openai.OpenAI(api_key=self.api_key, timeout=self.timeout)

        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(context)

        logger.info("Requesting notes from OpenAI", model=self.model)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            raw_content = response.choices[0].message.content
            return _extract_json_from_response(raw_content)

        except openai.APITimeoutError as e:
            raise AIProviderTimeout(f"OpenAI request timed out: {e}")
        except openai.RateLimitError as e:
            raise AIProviderRateLimited(f"OpenAI rate limited: {e}")
        except openai.APIError as e:
            raise AIProviderError(f"OpenAI API error: {e}")


# ── Google AI Provider (legacy/alternative) ────────────────────────


class GoogleAIProvider(AIProvider):
    """Google Generative AI provider (Gemini)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or settings.GOOGLE_AI_API_KEY
        self.model_name = model or settings.GOOGLE_AI_MODEL
        self.timeout = timeout or settings.AI_REQUEST_TIMEOUT

        if not self.api_key:
            raise ValueError("GOOGLE_AI_API_KEY is required for Google AI provider")

    def generate_structured_notes(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate structured notes using Google Generative AI."""
        import google.generativeai as genai

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model_name)

        prompt = _build_system_prompt() + "\n\n" + _build_user_prompt(context)

        logger.info("Requesting notes from Google AI", model=self.model_name)
        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )
            return _extract_json_from_response(response.text)

        except Exception as e:
            raise AIProviderError(f"Google AI error: {e}")


# ── Factory ────────────────────────────────────────────────────────


def create_ai_provider(provider_name: str | None = None) -> AIProvider:
    """Factory function to create the configured AI provider."""
    name = (provider_name or settings.AI_PROVIDER).lower()
    if name == "nvidia":
        return NvidiaProvider()
    elif name == "openai":
        return OpenAIProvider()
    elif name == "google":
        return GoogleAIProvider()
    else:
        raise ValueError(f"Unknown AI provider: {name}. Supported: nvidia, openai, google")

