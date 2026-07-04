"""CONSILIUM multi-agent research system (Phase 3).

A LangGraph StateGraph that turns a ticker into a structured research note:

    retrieval_agent (tool) ── used by ──▶ bull_agent
                                         bear_agent      ─┐
                                                          ├─▶ fact_checker_agent ─┐
    quant_agent (stub) ───────────────────────────────────────────────┐         │
                                                                       └─▶ synthesizer_agent ─▶ ResearchNote

Design rules honoured here (see docs/phase3-agents.md):
  * Every agent is its own file with a *scoped* system prompt and a Pydantic
    output schema — no mega-prompt, no raw-string hand-offs.
  * Bull/bear may only make claims that come from retrieval (no unsourced text).
  * The fact-checker re-queries retrieval *independently* per claim and forces
    exactly one label (SUPPORTED / CONTRADICTED / UNVERIFIABLE) — no free-text.
  * Reasoning is deterministic-over-retrieval today; each agent exposes an LLM
    seam so Claude can be dropped in later without touching the graph.
"""
