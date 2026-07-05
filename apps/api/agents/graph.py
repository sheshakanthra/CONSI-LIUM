"""LangGraph StateGraph wiring for the research system.

Topology (an explicit DAG, not a linear chain):

        ┌─────► bull ─────┐
  START ─┤                 ├─► fact_check ─► quant ─► synthesizer ─► END
        └─────► bear ─────┘

  * bull and bear have no dependencies -> they run **concurrently** in the first
    super-step (each opens its own DB session, see deps.py).
  * fact_check is the fan-in join: it waits for bull AND bear, because it must
    see every claim from both theses.
  * quant (a stub) then synthesizer run after the join.

WHY quant sits after the join rather than as a third parallel branch: LangGraph
schedules a node as soon as one predecessor completes, so a depth-1 quant edge
into the (depth-3) synthesizer would fire synthesizer early, before the
bull/bear/fact_check branch merged. Placing quant on the post-join path keeps a
single, unambiguous predecessor for synthesizer. quant ignores fact_check's
output — the edge is purely an ordering barrier — and its result is read from
state by the synthesizer.

Nodes are thin adapters: they pull inputs from state, call the agent object, and
write one output key back. Agent logic lives in the agent files; this module only
wires them and injects deps.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from agents.bear_agent import BearAgent
from agents.bull_agent import BullAgent
from agents.deps import AgentDeps, default_deps
from agents.fact_checker_agent import FactCheckerAgent
from agents.quant_agent import QuantAgent
from agents.state import ResearchState
from agents.synthesizer_agent import SynthesizerAgent


def build_research_graph(deps: AgentDeps):
    """Compile the research StateGraph against the given dependencies."""
    bull, bear = BullAgent(), BearAgent()
    fact_checker, quant, synthesizer = (
        FactCheckerAgent(),
        QuantAgent(),
        SynthesizerAgent(),
    )

    async def bull_node(state: ResearchState) -> dict:
        return {"bull": await bull.run(deps, state["ticker"])}

    async def bear_node(state: ResearchState) -> dict:
        return {"bear": await bear.run(deps, state["ticker"])}

    async def quant_node(state: ResearchState) -> dict:
        return {"quant": await quant.run(state["ticker"])}

    async def fact_check_node(state: ResearchState) -> dict:
        # Every claim from BOTH theses goes through the fact-checker.
        claims = [*state["bull"].claims, *state["bear"].claims]
        return {"fact_check": await fact_checker.run(deps, state["ticker"], claims)}

    async def synthesizer_node(state: ResearchState) -> dict:
        note = await synthesizer.run(
            state["ticker"],
            state["bull"],
            state["bear"],
            state["fact_check"],
            state["quant"],
        )
        return {"note": note}

    # Node names are suffixed "_agent" so they don't collide with the state
    # keys they write (LangGraph forbids a node named like a state channel).
    builder = StateGraph(ResearchState)
    builder.add_node("bull_agent", bull_node)
    builder.add_node("bear_agent", bear_node)
    builder.add_node("quant_agent", quant_node)
    builder.add_node("fact_checker_agent", fact_check_node)
    builder.add_node("synthesizer_agent", synthesizer_node)

    # Fan-out: bull and bear run concurrently.
    builder.add_edge(START, "bull_agent")
    builder.add_edge(START, "bear_agent")
    # Fan-in: the fact-checker waits for bull AND bear (same-depth join).
    builder.add_edge("bull_agent", "fact_checker_agent")
    builder.add_edge("bear_agent", "fact_checker_agent")
    # Post-join ordering: fact_check -> quant -> synthesizer.
    builder.add_edge("fact_checker_agent", "quant_agent")
    builder.add_edge("quant_agent", "synthesizer_agent")
    builder.add_edge("synthesizer_agent", END)

    return builder.compile()


@lru_cache(maxsize=1)
def _default_graph():
    """Compiled graph for the running service (built once, deps shared)."""
    return build_research_graph(default_deps())


async def run_research(ticker: str) -> ResearchState:
    """Run the full graph for a ticker and return the final typed state."""
    graph = _default_graph()
    result = await graph.ainvoke({"ticker": ticker})
    return result  # type: ignore[return-value]
