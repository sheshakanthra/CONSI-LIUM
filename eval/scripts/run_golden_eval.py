"""Deterministic golden-set eval — the fast, LLM-free CI gate.

Runs every golden entry through the real stack and checks *observable, exact*
properties — no LLM judge, so it's cheap, hermetic, and reproducible:

  * table_qa / document_qa : the answer contains the expected substring(s) AND
    carries a citation of the expected kind (table vs chunk) on the right page.
  * insufficient            : the system refuses (sufficient=False) and emits NO
    citation — the refusal guarantee.
  * research                : the full graph yields >= min supported claims, each
    with a citation, plus a real (non-placeholder) quant signal.

WHY this is separate from RAGAS: RAGAS measures *semantic* quality with an LLM
judge (see run_ragas.py). This measures *contractual* correctness — did we return
the right figure with the right provenance, and did we refuse when we should.
That's the property a regression gate must never let slip, and it needs no key.

Exit code is non-zero if any category accuracy falls below its threshold, so CI
can gate on it. Use ``--json`` to emit machine-readable results.

Run (inside the api container):
    PYTHONPATH=/app python run_golden_eval.py --golden-set /tmp/golden_set.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from _evalcommon import bootstrap_api_path, load_entries

bootstrap_api_path()

from app.db import SessionLocal  # noqa: E402
from retrieval.service import QAService  # noqa: E402


def _answer_ok(entry: dict, answer_text: str) -> bool:
    text = answer_text.lower()
    return all(sub.lower() in text for sub in entry.get("answer_contains", []))


def _citation_ok(entry: dict, citations: list) -> bool:
    expected = entry.get("expected_citation")
    if expected is None:
        return not citations  # refusal: must have NO citation
    if not citations:
        return False
    cite = citations[0]
    type_ok = expected["source_type"] in ("any", cite.source_type)
    page_ok = "page" not in expected or expected["page"] == cite.page_number
    return type_ok and page_ok


async def _eval_qa(svc: QAService, entry: dict) -> dict:
    async with SessionLocal() as session:
        ans = await svc.answer_question(session, entry["question"], entry["ticker"])

    checks = {
        "sufficient": ans.sufficient == entry["sufficient"],
        "answer": _answer_ok(entry, ans.answer),
        "citation": _citation_ok(entry, ans.citations),
    }
    return {
        "id": entry["id"],
        "category": entry["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "got_answer": ans.answer,
        "got_sufficient": ans.sufficient,
    }


async def _eval_research(entry: dict) -> dict:
    # Imported lazily: research needs the LangGraph stack + an LLM key, whereas
    # the QA path above does not. Keeping the import here lets the QA-only subset
    # run even in an environment where the graph deps aren't importable.
    from agents.graph import run_research

    state = await run_research(entry["ticker"])
    note = state["note"]
    supported = note.key_supported_claims
    checks = {
        "min_supported_claims": len(supported) >= entry.get("min_supported_claims", 1),
        "citations": (not entry.get("require_citations")) or bool(note.citations),
        "supported_claims_cited": all(c.citations for c in supported),
        "quant_real": (not entry.get("require_quant"))
        or (note.quant_signal is not None and not note.quant_signal.is_placeholder),
    }
    return {
        "id": entry["id"],
        "category": entry["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "n_supported": len(supported),
        "n_citations": len(note.citations),
    }


async def run(entries: list[dict], skip_research: bool) -> dict:
    svc = QAService()
    results: list[dict] = []
    for entry in entries:
        if entry["category"] == "research":
            if skip_research:
                continue
            results.append(await _eval_research(entry))
        else:
            results.append(await _eval_qa(svc, entry))
    return _summarize(results)


def _summarize(results: list[dict]) -> dict:
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    # Answerable accuracy = table_qa + document_qa (+ research) that fully passed.
    answerable_cats = {"table_qa", "document_qa", "research"}
    answerable = [r for r in results if r["category"] in answerable_cats]
    refusal = [r for r in results if r["category"] == "insufficient"]

    def acc(rows: list[dict]) -> float:
        return sum(r["passed"] for r in rows) / len(rows) if rows else float("nan")

    return {
        "results": results,
        "totals": {
            "n": len(results),
            "passed": sum(r["passed"] for r in results),
            "overall_accuracy": acc(results),
            "answer_accuracy": acc(answerable),
            "refusal_accuracy": acc(refusal),
            "by_category": {c: round(acc(rows), 4) for c, rows in by_cat.items()},
        },
    }


def _print_report(summary: dict) -> None:
    print("Golden-set deterministic eval")
    print("=" * 60)
    for r in summary["results"]:
        mark = "PASS" if r["passed"] else "FAIL"
        failed = [k for k, v in r["checks"].items() if not v]
        detail = "" if r["passed"] else f"  <- failed: {', '.join(failed)}"
        print(f"  [{mark}] {r['id']:<24} ({r['category']}){detail}")
    t = summary["totals"]
    print("-" * 60)
    for cat, a in t["by_category"].items():
        print(f"  {cat:<14} accuracy: {a:.1%}")
    print("-" * 60)
    print(f"  answer accuracy   : {t['answer_accuracy']:.1%}")
    print(f"  refusal accuracy  : {t['refusal_accuracy']:.1%}")
    print(f"  overall           : {t['overall_accuracy']:.1%} "
          f"({t['passed']}/{t['n']})")


def main() -> int:
    p = argparse.ArgumentParser(description="Deterministic golden-set eval / CI gate")
    p.add_argument("--golden-set", default=None)
    p.add_argument("--skip-research", action="store_true",
                   help="skip research entries (no LLM/graph needed)")
    p.add_argument("--min-answer-accuracy", type=float, default=0.90)
    p.add_argument("--min-refusal-accuracy", type=float, default=1.00)
    p.add_argument("--json", dest="as_json", action="store_true")
    args = p.parse_args()

    entries = load_entries(args.golden_set)
    summary = asyncio.run(run(entries, args.skip_research))

    if args.as_json:
        print(json.dumps(summary, indent=2))
    else:
        _print_report(summary)

    t = summary["totals"]
    ok = t["answer_accuracy"] >= args.min_answer_accuracy and (
        t["refusal_accuracy"] != t["refusal_accuracy"]  # NaN => no refusal cases
        or t["refusal_accuracy"] >= args.min_refusal_accuracy
    )
    if not ok:
        print(
            f"\nFAILED gate: answer {t['answer_accuracy']:.1%} "
            f"(>= {args.min_answer_accuracy:.0%}) / refusal {t['refusal_accuracy']:.1%} "
            f"(>= {args.min_refusal_accuracy:.0%})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
