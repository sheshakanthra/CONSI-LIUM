"""Unit tests for the shared output guardrail (agents.guardrails).

Offline and provider-free: the guardrail is decoupled from any LLM, so its retry
policy — succeed first try, recover on the second, or raise after exhausting —
is verified with a fake ``produce`` and no API key. This is the single place the
"no unvalidated agent output" guarantee is enforced, so it's worth pinning down.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agents.guardrails import SchemaValidationError, parse_with_retry


class _Shape(BaseModel):
    value: int


async def test_valid_first_attempt_no_retry():
    calls: list[int] = []

    async def produce(prompt: str, attempt: int):
        calls.append(attempt)
        return '{"value": 7}', {"attempt": attempt}

    obj, meta = await parse_with_retry(produce=produce, schema=_Shape, base_prompt="p")
    assert obj.value == 7
    assert meta == {"attempt": 0}
    assert calls == [0]  # exactly one call, no retry


async def test_recovers_on_second_attempt_with_stricter_prompt():
    prompts: list[str] = []

    async def produce(prompt: str, attempt: int):
        prompts.append(prompt)
        # First reply is malformed; second is valid.
        return ("not json" if attempt == 0 else '{"value": 3}'), attempt

    obj, meta = await parse_with_retry(produce=produce, schema=_Shape, base_prompt="BASE")
    assert obj.value == 3
    assert meta == 1
    # The retry prompt keeps the base and appends the stricter instruction.
    assert prompts[0] == "BASE"
    assert prompts[1].startswith("BASE")
    assert "your previous reply was invalid" in prompts[1]


async def test_empty_response_is_treated_as_invalid():
    async def produce(prompt: str, attempt: int):
        return ("" if attempt == 0 else '{"value": 1}'), None

    obj, _ = await parse_with_retry(produce=produce, schema=_Shape, base_prompt="p")
    assert obj.value == 1


async def test_raises_after_exhausting_retries():
    attempts: list[int] = []

    async def produce(prompt: str, attempt: int):
        attempts.append(attempt)
        return "still not json", None

    with pytest.raises(SchemaValidationError):
        await parse_with_retry(
            produce=produce, schema=_Shape, base_prompt="p", max_retries=2
        )
    assert attempts == [0, 1, 2]  # initial + 2 retries


async def test_on_invalid_hook_fires_only_on_failure():
    invalid: list[int] = []

    async def produce(prompt: str, attempt: int):
        return ("bad" if attempt == 0 else '{"value": 9}'), None

    await parse_with_retry(
        produce=produce,
        schema=_Shape,
        base_prompt="p",
        on_invalid=lambda attempt, exc: invalid.append(attempt),
    )
    assert invalid == [0]  # fired once, for the first (bad) attempt
