"""Shared output guardrail: schema-validation with stricter-reprompt retry.

WHY this module exists (and is not copy-pasted per agent): every reasoning agent
— bull, bear, fact-checker — must get a *schema-valid* object back from the LLM
or fail loudly; none may accept a raw string (CLAUDE.md: "no raw string handoffs
between agents"). That guarantee is one behaviour, so it lives in exactly one
place. Agents don't implement it and can't drift from it: they call
``deps.llm.structured(...)``, which delegates here.

The guardrail is deliberately decoupled from any provider. It takes a ``produce``
callable that turns a prompt into raw text (+ arbitrary metadata like token
usage), validates that text against the target Pydantic schema, and on failure
re-prompts once (by default) with the validator's own error appended — a cheap,
effective nudge that turns "almost-JSON" into valid JSON. If every attempt fails
it raises ``SchemaValidationError`` rather than returning something unvalidated.

Because it has no network/provider dependency, it is unit-testable on its own
(see tests/test_guardrails.py) — the retry policy is verified without a key.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
M = TypeVar("M")

# Appended to the ORIGINAL prompt on a retry. Keeping the base prompt intact and
# adding the concrete validator error is what makes the second attempt land.
_STRICTER_SUFFIX = (
    "\n\nIMPORTANT: your previous reply was invalid: {error}. Reply with ONLY a "
    "JSON object that exactly matches the required schema — no prose, no markdown, "
    "no code fences."
)

# The validation failures we treat as "retryable bad output" (as opposed to a
# programming error, which should propagate). Malformed JSON, schema mismatch,
# and an empty response all mean "the model didn't comply — ask again".
_RETRYABLE = (ValidationError, ValueError, json.JSONDecodeError)


class SchemaValidationError(RuntimeError):
    """Raised when no attempt produced a schema-valid result."""


async def parse_with_retry(
    *,
    produce: Callable[[str, int], Awaitable[tuple[str | None, M]]],
    schema: type[T],
    base_prompt: str,
    max_retries: int = 1,
    on_attempt: Callable[[int], None] | None = None,
    on_invalid: Callable[[int, Exception], None] | None = None,
) -> tuple[T, M]:
    """Validate ``produce``'s output against ``schema``, retrying on failure.

    Args:
        produce: async ``(prompt, attempt) -> (raw_text, meta)``. ``meta`` is
            passed through untouched (the LLM client uses it for token usage).
        schema: the Pydantic model the raw text must parse into.
        base_prompt: the user prompt; retries append the stricter suffix to THIS,
            so the error from one attempt never compounds into the next.
        max_retries: extra attempts after the first (default 1 => up to 2 calls).
        on_attempt / on_invalid: optional observability hooks (logging), so this
            module needs no logger of its own and callers keep their log format.

    Returns:
        ``(validated_instance, meta_from_the_successful_call)``.

    Raises:
        SchemaValidationError: if every attempt failed validation.
    """
    prompt = base_prompt
    last_err: Exception | None = None

    for attempt in range(max_retries + 1):
        if on_attempt is not None:
            on_attempt(attempt)

        text, meta = await produce(prompt, attempt)
        try:
            if not text:
                raise ValueError("empty LLM response")
            return schema.model_validate_json(text), meta
        except _RETRYABLE as exc:
            last_err = exc
            if on_invalid is not None:
                on_invalid(attempt, exc)
            prompt = base_prompt + _STRICTER_SUFFIX.format(error=str(exc)[:200])

    raise SchemaValidationError(
        f"failed schema validation for {schema.__name__} after "
        f"{max_retries + 1} attempt(s): {last_err}"
    ) from last_err
