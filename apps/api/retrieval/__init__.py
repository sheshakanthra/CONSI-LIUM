"""CONSILIUM retrieval layer (Phase 2).

Embeds ingested text into pgvector and answers questions over it with
citations:

    question + ticker
        -> router (heuristic: structured-number? -> table path, else document)
        -> retriever (hybrid: vector similarity + keyword, scoped per ticker)
        -> extractive answerer  (LLM seam left for later)
        -> Answer(text, citations, confidence, sufficient?)

Every answer carries source ids + page numbers and can say "insufficient
evidence" when retrieval doesn't support a claim.
"""
