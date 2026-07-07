"""Fact-checker eval — validates the project's core differentiator.

RAGAS measures whether *retrieval* is faithful. This measures whether the
**fact-checker** actually catches bad claims — which is the whole point of the
system. We feed it claims whose truth we know and assert the label:

  * SUPPORTED    — claims that match the filing's real figures / prose.
  * CONTRADICTED — claims with a WRONG figure the tables can disprove.
  * UNVERIFIABLE — claims about facts simply not in the corpus.

The set deliberately spans both fact-checker paths:
  * deterministic  — exact numeric match / table contradiction / no-evidence
    (no LLM; free and stable), and
  * LLM-adjudicated — narrative claims the code escalates to the model.

So the accuracy number reflects the real end-to-end checker, model included.
Reports overall accuracy, a per-class confusion matrix, and every mismatch.

Run (inside the api container, with a working LLM key):
    PYTHONPATH=/app python eval_factchecker.py --golden-set /tmp/golden_set.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from _evalcommon import bootstrap_api_path

bootstrap_api_path()

from agents.deps import AgentDeps  # noqa: E402
from agents.fact_checker_agent import ClaimLabel, FactCheckerAgent  # noqa: E402
from agents.llm_client import LLMClient  # noqa: E402
from agents.retrieval_agent import RetrievalAgent  # noqa: E402
from agents.types import Claim, ClaimStance  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from retrieval.types import Citation, Confidence  # noqa: E402

# (ticker, claim_text, expected_label, path_hint). path_hint documents which
# branch we expect to exercise; it isn't asserted, only printed.
CASES: list[tuple[str, str, str, str]] = [
    # --- SUPPORTED: real figures (deterministic exact-value match) -----------
    ("ACME", "Revenue for Q1 FY27 is 1,245.", "SUPPORTED", "deterministic"),
    ("ACME", "EBITDA for Q1 FY27 is 312.", "SUPPORTED", "deterministic"),
    ("ACME", "Net profit is 188.", "SUPPORTED", "deterministic"),
    ("ACME", "EPS is 9.40.", "SUPPORTED", "deterministic"),
    ("GLOBEX", "Cloud Services revenue in FY26 is 4,120.", "SUPPORTED", "deterministic"),
    ("GLOBEX", "Total revenue in FY26 is 7,930.", "SUPPORTED", "deterministic"),
    # --- CONTRADICTED: wrong figures the tables disprove (deterministic) ------
    ("ACME", "Revenue for Q1 FY27 is 5,000.", "CONTRADICTED", "deterministic"),
    ("ACME", "Net profit is 250.", "CONTRADICTED", "deterministic"),
    ("ACME", "EPS is 15.00.", "CONTRADICTED", "deterministic"),
    ("GLOBEX", "Total revenue in FY26 is 9,999.", "CONTRADICTED", "deterministic"),
    # --- UNVERIFIABLE: facts not in the corpus (deterministic no-evidence) ----
    ("ACME", "The company employs 40,000 people.", "UNVERIFIABLE", "deterministic"),
    ("ACME", "The CEO is Jane Doe.", "UNVERIFIABLE", "deterministic"),
    ("GLOBEX", "The company announced a share buyback.", "UNVERIFIABLE", "deterministic"),
    # --- SUPPORTED: narrative claims (escalated to the LLM) -------------------
    ("ACME", "The board recommended an interim dividend.", "SUPPORTED", "llm"),
    ("GLOBEX", "Guidance for the coming year was maintained.", "SUPPORTED", "llm"),
    ("GLOBEX", "Management highlighted a reduction in net debt.", "SUPPORTED", "llm"),
]

# A placeholder citation so the Claim schema (citations: min_length=1) is
# satisfied. The fact-checker IGNORES it — it re-queries retrieval independently
# by the claim's text — so its value never influences the verdict.
_DUMMY_CITATION = Citation(source_type="chunk", source_id=-1, page_number=None)


def _make_claim(idx: int, text: str) -> Claim:
    return Claim(
        id=f"eval-{idx}",
        stance=ClaimStance.BULL,
        text=text,
        probe="(fact-checker eval)",
        confidence=Confidence.MEDIUM,
        citations=[_DUMMY_CITATION],
    )


async def run() -> dict:
    deps = AgentDeps(
        retrieval=RetrievalAgent(), session_factory=SessionLocal, llm=LLMClient()
    )
    checker = FactCheckerAgent()

    labels = [lbl.value for lbl in ClaimLabel]
    confusion = {exp: {got: 0 for got in labels} for exp in labels}
    rows: list[dict] = []

    for ticker in sorted({c[0] for c in CASES}):
        group = [(i, c) for i, c in enumerate(CASES) if c[0] == ticker]
        claims = [_make_claim(i, c[1]) for i, c in group]
        report = await checker.run(deps, ticker, claims)
        for (_i, (_t, text, expected, hint)), checked in zip(group, report.checked):
            got = checked.label.value
            confusion[expected][got] += 1
            rows.append({
                "ticker": ticker,
                "claim": text,
                "expected": expected,
                "got": got,
                "path_hint": hint,
                "correct": got == expected,
                "rationale": checked.rationale,
            })

    correct = sum(r["correct"] for r in rows)
    return {
        "results": rows,
        "confusion": confusion,
        "accuracy": correct / len(rows) if rows else float("nan"),
        "n": len(rows),
        "correct": correct,
    }


def _print_report(summary: dict) -> None:
    print("Fact-checker eval (known-true / known-false / unverifiable)")
    print("=" * 68)
    for r in summary["results"]:
        mark = "OK " if r["correct"] else "XX "
        print(f"  [{mark}] exp={r['expected']:<12} got={r['got']:<12} "
              f"({r['path_hint']}) {r['claim']}")
        if not r["correct"]:
            print(f"         rationale: {r['rationale']}")
    print("-" * 68)
    labels = list(next(iter(summary["confusion"].values())).keys())
    print("  confusion (rows=expected, cols=got):")
    print("               " + "".join(f"{l[:5]:>8}" for l in labels))
    for exp, gots in summary["confusion"].items():
        print(f"    {exp:<12}" + "".join(f"{gots[l]:>8}" for l in labels))
    print("-" * 68)
    print(f"  accuracy: {summary['accuracy']:.1%} "
          f"({summary['correct']}/{summary['n']})")


def main() -> int:
    p = argparse.ArgumentParser(description="Fact-checker accuracy eval / CI gate")
    # golden-set flag accepted for interface parity / future golden-driven cases.
    p.add_argument("--golden-set", default=None)
    p.add_argument("--min-accuracy", type=float, default=0.90)
    p.add_argument("--json", dest="as_json", action="store_true")
    args = p.parse_args()

    summary = asyncio.run(run())
    if args.as_json:
        print(json.dumps(summary, indent=2))
    else:
        _print_report(summary)

    if summary["accuracy"] < args.min_accuracy:
        print(f"\nFAILED gate: fact-checker accuracy {summary['accuracy']:.1%} "
              f"< {args.min_accuracy:.0%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
