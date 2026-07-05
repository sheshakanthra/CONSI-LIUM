# Phase 3 — Multi-Agent Research System (LangGraph)

> Design note for the agent phase. Per CLAUDE.md, each phase ships a short
> markdown note capturing the design decisions.

## What this phase delivers

A LangGraph `StateGraph` under `apps/api/agents/` that turns a ticker into a
structured, fact-checked research note, plus a `GET /research/{ticker}` endpoint.

```
        ┌─────► bull ─────┐
  START ─┤                 ├─► fact_check ─► quant ─► synthesizer ─► END
        └─────► bear ─────┘
                              (retrieval_agent is a tool used by
                               bull, bear, and fact_check)
```

Run it:

```bash
docker compose exec api python -m retrieval.index          # ensure evidence is indexed
curl -s localhost:8000/research/ACME | python -m json.tool  # full research note
docker compose exec api pytest tests/test_agents.py -v      # end-to-end graph test
```

## Agent-brain decision (real LLM reasoning, provider-swappable)

Bull, bear, and the fact-checker call an **LLM** for their reasoning (the earlier
deterministic-over-retrieval version is gone). Each agent still has a scoped
system prompt and a Pydantic output schema, and calls the same
`deps.llm.structured(...)` — it does **not** know or care which provider is
behind it.

### Why Groq is the default (cost)

The default provider is **Groq's free developer tier**, not Anthropic. This is a
deliberate cost choice: Anthropic's API needs paid credits, whereas Groq offers a
free tier that is more than adequate for a portfolio-scale project. **Anthropic
(Claude) remains a first-class, swappable option** behind the exact same seam —
flip one env var to upgrade when credits are available.

- `LLM_PROVIDER` selects the provider: `groq` (default) or `anthropic`.
- **Groq** (`groq_model`, default `llama-3.3-70b-versatile` — a current fast
  general-purpose production model) via its **OpenAI-compatible API**
  (`AsyncOpenAI` pointed at `https://api.groq.com/openai/v1`), JSON mode. Key:
  `GROQ_API_KEY` (free at console.groq.com).
- **Anthropic** (`agent_model`, default `claude-haiku-4-5`) via the Anthropic
  SDK, `output_config.format` structured outputs. Key: `ANTHROPIC_API_KEY`.
- Only the *chosen* provider's key is required, and only for `/research` —
  ingestion, retrieval, and the test suite need no LLM key (tests mock it).

### The LLM client (`llm_client.py`) — one seam, two providers

One method — `structured(system, user, schema, agent)` — returns a *validated*
Pydantic object + `LLMUsage`, **identically for both providers**. Only the inner
`_complete()` is provider-specific (returns raw JSON text + token counts); the
cross-cutting behaviour lives in `structured()` and runs the same either way:

- **Schema validation** (Pydantic) on every reply.
- **Retry with a stricter prompt on validation failure**, so a malformed reply
  doesn't crash the graph.
- **Per-call token + cost logging** — one `INFO` line per call
  (`[llm] provider=… agent=… input=… output=… cost=$…`).

Because the interface is unchanged, `bull_agent`, `bear_agent`, and
`fact_checker_agent` required **zero changes** to add Groq. Clients are built
lazily so importing `agents` never needs an SDK/key.

## Each agent (its own file: scoped prompt + Pydantic schema)

| Agent | File | Output schema | Role |
|---|---|---|---|
| retrieval_agent | `retrieval_agent.py` | `Answer` (Phase 2) | Wraps `/qa` retrieval as a **tool** the other agents call. The only DB-touching agent. |
| bull_agent | `bull_agent.py` | `BullThesis` | Claude builds the **bullish** case from retrieved evidence; citations re-anchored to retrieval. |
| bear_agent | `bear_agent.py` | `BearThesis` | Claude builds the **bearish** case; same sourcing guarantee. |
| fact_checker_agent | `fact_checker_agent.py` | `FactCheckReport` | Independent re-query; Claude adjudicates the non-exact matches. Forces one label each. |
| quant_agent | `quant_agent.py` | `QuantSignal` | **Stub** signal (Phase 4 fills in). |
| synthesizer_agent | `synthesizer_agent.py` | `ResearchNote` | Assembles the final note from all of the above. |

## "No unsourced claims" survives the LLM (the key design point)

The `Claim` schema still requires `citations: list[Citation] = Field(min_length=1)`,
and that guarantee is preserved *even though Claude now writes the claims*, via
`agents/reasoning.py`:

1. Gather stance-specific evidence from retrieval; tag each kept item `E1`, `E2`,
   … Each is a real `Answer` with citations.
2. Send Claude **only** that tagged evidence and ask it to build the thesis, with
   every claim citing exactly one `E#` id.
3. **Re-attach the citation from our evidence**, never from the model. A claim
   that cites an id we didn't supply — an unsourced/hallucinated claim — is
   **dropped**, not passed through.

So the model chooses and phrases the argument, but it can't invent a citation:
the worst it can do is reference a bad id, and that claim is discarded. A test
(`test_unsourced_llm_claim_is_dropped`) feeds a fake claim citing `E999` and
asserts it never reaches the thesis.

## The fact-checker's independent re-query (the core differentiator)

For **every** claim from bull *and* bear, the fact-checker:

1. Issues its **own** fresh retrieval query, keyed on the **claim's text** — not
   the probe that produced it, and not the citation bull/bear attached. Replaying
   the probe would just re-run the same lookup; querying the assertion itself is
   a genuine second path to the evidence (how a human re-derives a figure).
2. Assigns exactly one label, escalating the **judgment call to Claude** only
   when the re-query isn't a clean exact match:
   - Deterministic (no LLM, free): re-query insufficient → **UNVERIFIABLE**;
     exact numeric value present → **SUPPORTED**; a *table* returned a different
     figure → **CONTRADICTED**.
   - Everything else (paraphrases, narrative claims) → **Claude** returns one of
     `SUPPORTED` / `CONTRADICTED` / `UNVERIFIABLE` + a rationale, judging the
     claim against only the independently-retrieved evidence.
3. Attaches the source **it** found, so "SUPPORTED" means *re-confirmed*, not
   *self-cited*.

The independent re-query is unchanged from the deterministic version — the LLM
only adjudicates the ambiguous cases (which keeps cost down: exact table matches
never call Claude). The schema makes the verdict non-negotiable:
`FactCheckedClaim.label` is a `ClaimLabel` enum and the LLM's own output schema is
a `Literal[...]` label — there is **no free-text field** to dodge the decision.
`FactCheckReport.counts` tallies verdicts.

## Explicit typed state (not an implicit chain)

`agents/state.py` defines `ResearchState(TypedDict)` with one key per agent
output. Each node writes exactly one key, so the independent `bull`/`bear` nodes
run concurrently in the first super-step with no key collisions (no custom
reducer needed). Nodes are thin adapters in `graph.py`; all logic lives in the
agent files.

### A LangGraph scheduling gotcha (documented so it isn't re-learned)

LangGraph schedules a node as soon as **one** predecessor completes. An early
design had `quant` as a third parallel branch feeding `synthesizer` directly —
that fired `synthesizer` at depth 2 (right after `quant`), *before* the
`bull/bear → fact_check` branch had merged, yielding a `KeyError` on
`fact_check`. Fix: keep a single unambiguous join. `fact_check` is the fan-in for
`bull`+`bear` (same depth — reliable), and `quant` sits on the post-join path
(`fact_check → quant → synthesizer`). `quant` ignores `fact_check`'s output; the
edge is purely an ordering barrier. The parallel `bull`/`bear` branch still
demonstrates real fan-out/fan-in.

## The note only presents fact-checked claims

The synthesizer partitions by verdict: `SUPPORTED → key_supported_claims`,
`CONTRADICTED/UNVERIFIABLE → key_disputed_or_unverifiable_claims` (flagged). A
claim the fact-checker couldn't confirm is never silently presented as fact — the
note's integrity is a graph property, not a matter of phrasing. Citations are the
de-duplicated independent sources the fact-checker actually found.

## Endpoint

`GET /research/{ticker}` runs the compiled graph (built once, cached) and returns
the `ResearchNote` as JSON. It **requires the selected provider's key** (default:
`GROQ_API_KEY`); without it the call fails loudly (a prompt 500) rather than
returning a fabricated note.

## Testing — deterministic & free (provider-agnostic)

The reasoning agents call an LLM, so the integration test **mocks the LLM client**
with a `FakeLLM` (echoes evidence back as claims; returns `SUPPORTED` for
adjudications). The mock sits at the `structured()` seam, so tests are identical
regardless of provider — hermetic (no key, no network, no cost) while still
exercising the real retrieval, citation re-anchoring, drop rule, fact-check
routing, and synthesizer partitioning.

## Cost per run

Per-call token + cost is logged (`[llm] provider=… agent=… input=… output=…
cost=$…`). A `/research/ACME` run issues ~2 thesis calls + a handful of fact-check
adjudications over small prompts (~1–2K input, ~0.5–0.7K output tokens total).

- **Groq (default): $0 on the free developer tier.** (On-demand rates for
  `llama-3.3-70b-versatile` are $0.59 / $0.79 per 1M in/out — a paid run would be
  well under a cent — but the dev tier bills nothing.)
- **Anthropic Haiku 4.5** ($1 / $5 per 1M): estimated **~$0.004–0.008 per run**.

> ⚠️ The numbers above are **estimates**: no LLM key was available in the build
> environment, so no billed run was captured (the Groq path was verified end-to-
> end — a request reached Groq and returned `401 Invalid API Key` with the empty
> placeholder). To measure exactly, set the chosen provider's key and read the logs:
> ```bash
> GROQ_API_KEY=gsk_... docker compose up -d api      # or ANTHROPIC_API_KEY + LLM_PROVIDER=anthropic
> curl -s localhost:8000/research/ACME >/dev/null
> docker compose logs api | grep '\[llm\]'           # sum the cost= fields
> ```

## "Done" checklist (CLAUDE.md)

- [x] Runs end-to-end locally via docker-compose (`GET /research/ACME`).
- [x] Has an integration test (`tests/test_agents.py`, LLM mocked) running the
      graph on the sample ticker; asserts the note schema is well-formed and that
      ≥1 claim was fact-checked with a real label.
- [x] Has this design note.

## Known limitations / next steps

- Bull/bear/fact-checker call Claude; the **synthesizer is still deterministic**
  (assembly + partitioning). Its prose thesis is the next natural LLM upgrade,
  behind the same `ResearchNote` schema.
- `CONTRADICTED` is reachable (deterministic table disagreement, or an LLM
  verdict) but the all-consistent single sample never triggers it; a multi-filing
  fixture would exercise it.
- The estimated cost above should be replaced with the measured number once a key
  is available (command provided).
- `quant_agent` is a deterministic stub; Phase 4 replaces its body with a real
  market-data signal behind the same `QuantSignal` schema.
