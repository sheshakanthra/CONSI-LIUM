"""Answer synthesis from retrieved chunks — extractive now, LLM-ready later.

WHY extractive first (decided with the user): it needs no API key, runs fully
offline in the docker stack, and makes the citation tests deterministic. The
answer is the retrieved sentence that best overlaps the question's content
words, so it's always grounded in — and traceable to — a specific chunk.

THE LLM SEAM: ``AnswerSynthesizer`` is the swap point. A future
``ClaudeAnswerer`` implementing ``synthesize(question, contexts)`` can generate
fluent prose from the same retrieved contexts without changing the service,
router, retriever, or citation plumbing.

Grounding is also what powers "insufficient evidence": if no retrieved sentence
shares a content word with the question, we refuse to answer rather than emit
the top chunk regardless of relevance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from retrieval.retriever import RetrievedChunk

# Tiny stopword list — enough to stop function words from creating false
# "overlap". Not linguistically complete on purpose; this is extraction, not NLP.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
        "was", "were", "be", "been", "what", "which", "who", "whom", "how", "did",
        "do", "does", "with", "by", "at", "as", "that", "this", "it", "its", "their",
        "there", "was", "about", "from", "into", "over", "than", "then",
    }
)


class AnswerSynthesizer(Protocol):
    """The seam: turn a question + retrieved contexts into answer text.

    Extractive today; a ClaudeAnswerer could implement the same signature.
    """

    def synthesize(self, question: str, contexts: list[str]) -> str: ...


@dataclass
class DocAnswer:
    """Result of extractive document answering."""

    text: str
    sufficient: bool
    chunk: RetrievedChunk | None
    # How many question content-words appeared in the chosen sentence.
    overlap: int


def _content_terms(question: str) -> set[str]:
    # Length >= 3: we match terms as substrings (cheap stemming, so "recommend"
    # hits "recommended"), and 1-2 char fragments like the "s" from "CEO's"
    # would substring-match unrelated words ("industrieS") and fabricate
    # overlap. Requiring length >= 3 keeps the grounding check honest.
    return {
        t
        for t in re.findall(r"[a-z0-9]+", question.lower())
        if t not in _STOPWORDS and len(t) >= 3
    }


def _split_sentences(text: str) -> list[str]:
    # Split on sentence punctuation OR newlines; keep non-empty trimmed pieces.
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _sentence_overlap(sentence: str, terms: set[str]) -> int:
    low = sentence.lower()
    # Substring match so "recommend" hits "recommended"; cheap stemming stand-in.
    return sum(1 for t in terms if t in low)


class ExtractiveAnswerer:
    """Default answerer: pick the best-matching retrieved sentence."""

    def answer(self, question: str, retrieved: list[RetrievedChunk]) -> DocAnswer:
        terms = _content_terms(question)
        best: tuple[int, str, RetrievedChunk] | None = None  # (overlap, sentence, chunk)

        for chunk in retrieved:
            for sentence in _split_sentences(chunk.text):
                overlap = _sentence_overlap(sentence, terms)
                if overlap == 0:
                    continue
                if best is None or overlap > best[0]:
                    best = (overlap, sentence, chunk)

        if best is None:
            return DocAnswer(text="", sufficient=False, chunk=None, overlap=0)

        overlap, sentence, chunk = best
        return DocAnswer(text=sentence, sufficient=True, chunk=chunk, overlap=overlap)
