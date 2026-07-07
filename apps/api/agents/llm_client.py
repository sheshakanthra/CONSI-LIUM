"""LLM client wrapper for the reasoning agents — provider-agnostic.

One method, ``structured(...)``, returns a validated Pydantic object plus
token/cost usage. Two providers sit behind it, chosen by ``LLM_PROVIDER``:

- **groq** (default): Groq's free developer tier via its OpenAI-COMPATIBLE API
  (``AsyncOpenAI`` pointed at ``https://api.groq.com/openai/v1``), using JSON mode
  (``response_format={"type": "json_object"}``) with the target schema embedded in
  the system prompt. Default model ``llama-3.3-70b-versatile``.
- **anthropic**: Claude via the Anthropic SDK, using ``output_config.format``
  (structured outputs). Default model ``claude-haiku-4-5``.

The important property: **schema validation, retry-with-stricter-prompt, and
token/cost logging are provider-agnostic** — they live in ``structured()`` and
run identically for both. Only ``_complete()`` is provider-specific, and it just
returns ``(raw_text, input_tokens, output_tokens)``. So bull/bear/fact-checker
call the exact same ``structured(system, user, schema, agent)`` regardless of
provider, with zero changes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from agents.guardrails import SchemaValidationError, parse_with_retry
from app.config import Settings, get_settings

logger = logging.getLogger("consilium.agents.llm")

T = TypeVar("T", bound=BaseModel)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# USD per 1M tokens (input, output). Used only for cost logging. Groq's *dev*
# tier is free ($0); the listed rates are its paid/on-demand prices, logged so
# the number is meaningful if you move off the free tier. Unknown models log $0.
_PRICES: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    # Groq (on-demand rates; free dev tier is $0)
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
}


class AgentLLMError(RuntimeError):
    """Raised when an LLM call can't produce a schema-valid result."""


class LLMUsage(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = _PRICES.get(model, (0.0, 0.0))
    return round(input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price, 6)


def _schema_for(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Anthropic-compatible JSON schema (additionalProperties:false + required)."""
    schema = model_cls.model_json_schema()

    def _tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for value in node.values():
                _tighten(value)
        elif isinstance(node, list):
            for value in node:
                _tighten(value)

    _tighten(schema)
    return schema


def _json_instruction(model_cls: type[BaseModel]) -> str:
    """System-prompt addendum for JSON-mode providers (Groq).

    Groq's json_object mode requires the word "json" to appear in the messages,
    and the model needs the target shape — so we spell out the schema. Validation
    still happens client-side via Pydantic (see structured()).
    """
    schema = json.dumps(_schema_for(model_cls), separators=(",", ":"))
    return (
        "You must respond with ONLY a single valid JSON object — no prose, no "
        "markdown, no code fences. The object must conform to this JSON schema:\n"
        + schema
    )


class LLMClient:
    """Provider-agnostic structured-output client (Groq or Anthropic)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._provider = (self._settings.llm_provider or "groq").strip().lower()
        if self._provider == "groq":
            self._model = self._settings.groq_model
        elif self._provider == "anthropic":
            self._model = self._settings.agent_model
        else:
            raise AgentLLMError(
                f"unknown LLM_PROVIDER {self._provider!r} (expected 'groq' or 'anthropic')"
            )
        self._max_tokens = self._settings.agent_max_tokens
        self._client = None  # lazily constructed per provider

    def _get_client(self):
        if self._client is None:
            # Local imports so `import agents` never hard-requires an SDK/key.
            if self._provider == "anthropic":
                from anthropic import AsyncAnthropic

                self._client = AsyncAnthropic(api_key=self._settings.anthropic_api_key)
            else:  # groq via OpenAI-compatible client
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(
                    api_key=self._settings.groq_api_key, base_url=_GROQ_BASE_URL
                )
        return self._client

    async def _complete(
        self, system: str, user: str, schema: type[BaseModel]
    ) -> tuple[str | None, int, int]:
        """Provider-specific call -> (raw JSON text, input_tokens, output_tokens)."""
        client = self._get_client()

        if self._provider == "anthropic":
            response = await client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": _schema_for(schema)}},
            )
            text = next((b.text for b in response.content if b.type == "text"), None)
            return text, response.usage.input_tokens, response.usage.output_tokens

        # groq (OpenAI-compatible): JSON mode + schema spelled out in the system prompt.
        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system + "\n\n" + _json_instruction(schema)},
                {"role": "user", "content": user},
            ],
        )
        usage = response.usage
        return (
            response.choices[0].message.content,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        agent: str,
        max_retries: int = 1,
    ) -> tuple[T, LLMUsage]:
        """Call the configured LLM and return (validated object, usage).

        The schema-validation + stricter-reprompt retry is NOT implemented here —
        it's the shared guardrail in ``agents.guardrails.parse_with_retry`` that
        every agent goes through. This method only supplies the provider-specific
        ``produce`` step (one raw completion + usage) and the logging hooks; the
        retry policy is identical for Groq/Anthropic because it lives in one place.
        """

        async def produce(prompt: str, attempt: int) -> tuple[str | None, LLMUsage]:
            # Request line — fires before the provider call (so it's visible even
            # if the call errors); the usage/cost line fires right after.
            logger.info(
                "[llm] provider=%s agent=%s model=%s calling (attempt=%d)",
                self._provider, agent, self._model, attempt,
            )
            text, input_tokens, output_tokens = await self._complete(system, prompt, schema)
            usage = LLMUsage(
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=_estimate_cost(self._model, input_tokens, output_tokens),
            )
            logger.info(
                "[llm] provider=%s agent=%s model=%s input=%d output=%d cost=$%.6f attempt=%d",
                self._provider, agent, usage.model, usage.input_tokens,
                usage.output_tokens, usage.cost_usd, attempt,
            )
            return text, usage

        def _log_invalid(attempt: int, exc: Exception) -> None:
            logger.warning(
                "[llm] provider=%s agent=%s invalid response (attempt=%d): %s",
                self._provider, agent, attempt, exc,
            )

        try:
            return await parse_with_retry(
                produce=produce,
                schema=schema,
                base_prompt=user,
                max_retries=max_retries,
                on_invalid=_log_invalid,
            )
        except SchemaValidationError as exc:
            # Preserve the public contract: agents catch AgentLLMError, not the
            # guardrail's internal error type.
            raise AgentLLMError(
                f"LLM call for {agent} ({self._provider}) {exc}"
            ) from exc
