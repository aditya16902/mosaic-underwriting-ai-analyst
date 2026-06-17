"""
Agent Eval Runner
Runs the Text-to-SQL agent against the golden question fixtures and scores
both the SQL generation layer (deterministic + schema check) and the
interpretation layer (LLM judge).

Usage:
  python evals/runners/agent_eval_runner.py                          # all fixtures, v1
  python evals/runners/agent_eval_runner.py --fixture agent_easy_direct_lookup
  python evals/runners/agent_eval_runner.py --prompt-version v2      # run bad prompts
  python evals/runners/agent_eval_runner.py --save-baseline          # update baseline after a good run
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES_DIR = ROOT / "evals" / "fixtures"
RESULTS_DIR  = ROOT / "evals" / "results"
RESULTS_DIR.mkdir(exist_ok=True)

from backend.agents.text_to_sql.agent import run_agent, _get_latest_run_data
from evals.judges.sql_comparator import compare_sql_results, check_schema_adherence
from evals.judges.agent_judge import evaluate_agent_answer


def _load_agent_fixtures() -> list:
    return sorted(FIXTURES_DIR.glob("agent_*.json"))


def _score_sql_layer(fixture: dict, sql: str, sql_result: dict, db_path: Path) -> dict:
    """Deterministic scoring: validity, schema adherence, reference comparison."""
    gt = fixture["ground_truth"]

    sql_validity = bool(sql_result.get("success"))

    schema_check = check_schema_adherence(sql, gt.get("schema_columns_allowed", []))

    comparison = compare_sql_results(
        db_path=db_path,
        reference_sql=fixture.get("reference_sql"),
        agent_result=sql_result,
    )

    if comparison["comparable"]:
        sql_correctness = 1.0 if comparison["values_match"] else 0.0
    else:
        # No reference SQL (adversarial fixtures) — correctness assessed via judge instead
        sql_correctness = None

    return {
        "sql_validity": sql_validity,
        "schema_adherence": schema_check["adherent"],
        "hallucinated_terms_found": schema_check["hallucinated_terms_found"],
        "sql_correctness": sql_correctness,
        "comparison_detail": comparison,
    }


def run_fixture(fixture_path: Path, prompt_version: str = "v1", run_llm: bool = True) -> dict:
    fixture = json.loads(fixture_path.read_text())
    fixture_id = fixture["fixture_id"]
    difficulty = fixture.get("difficulty", "unknown")
    question = fixture["question"]

    print(f"\n  {'─'*50}")
    print(f"  Fixture: {fixture_id}  [{difficulty}]  prompt={prompt_version}")
    print(f"  Question: {question}")
    print(f"  {'─'*50}")

    result = {
        "fixture_id": fixture_id,
        "difficulty": difficulty,
        "prompt_version": prompt_version,
        "question": question,
        "run_at": datetime.utcnow().isoformat() + "Z",
        "sql_layer": {},
        "judge_eval": {},
        "errors": [],
    }

    if not run_llm:
        print(f"  [Agent] Skipped (--no-llm)")
        return result

    try:
        db_path, _ = _get_latest_run_data(None)
        if db_path is None:
            result["errors"].append("No report run available to query against.")
            print(f"  [Agent] ERROR: no run data found — generate a report first.")
            return result

        agent_out = run_agent(question=question, prompt_version=prompt_version)
    except Exception as e:
        result["errors"].append(f"Agent error: {e}")
        print(f"  [Agent] ERROR: {e}")
        import traceback; traceback.print_exc()
        return result

    sql = agent_out.get("sql") or ""
    sql_result = agent_out.get("result") or {"success": False, "row_count": 0, "rows": [], "columns": []}
    answer = agent_out.get("answer", "")

    # ── SQL layer (deterministic) ────────────────────────────────────────────
    try:
        sql_layer = _score_sql_layer(fixture, sql, sql_result, db_path)
        result["sql_layer"] = sql_layer
        sc = sql_layer["sql_correctness"]
        sc_str = f"{sc:.2f}" if isinstance(sc, float) else "N/A (no reference)"
        print(f"  [SQL Layer] validity={sql_layer['sql_validity']}  "
              f"schema_adherence={sql_layer['schema_adherence']}  "
              f"correctness={sc_str}")
        if sql_layer["hallucinated_terms_found"]:
            print(f"    ⚠️  Hallucinated terms: {sql_layer['hallucinated_terms_found']}")
    except Exception as e:
        result["errors"].append(f"SQL layer scoring error: {e}")
        print(f"  [SQL Layer] ERROR: {e}")

    # ── Interpretation layer (LLM judge) ─────────────────────────────────────
    try:
        judge_scores = evaluate_agent_answer(
            ground_truth=fixture["ground_truth"],
            question=question,
            report_context=agent_out.get("report_context", ""),
            sql=sql,
            sql_result=sql_result,
            answer=answer,
        )
        result["judge_eval"] = judge_scores
        print(f"  [Judge] Overall: {judge_scores.get('overall', 0):.2f}  "
              f"| faithfulness={judge_scores.get('answer_faithfulness', 'N/A')}  "
              f"| grounding={judge_scores.get('report_grounding', 'N/A')}  "
              f"| tone={judge_scores.get('tone_directness', 'N/A')}  "
              f"| refusal={judge_scores.get('refusal_correctness', 'N/A')}")
    except Exception as e:
        result["errors"].append(f"Judge error: {e}")
        print(f"  [Judge] ERROR: {e}")
        import traceback; traceback.print_exc()

    result["agent_answer"] = answer
    result["agent_sql"] = sql
    result["sql_attempts"] = agent_out.get("attempts")

    return result


def run_all(fixture_filter: Optional[str], prompt_version: str, save_baseline: bool, run_llm: bool):
    all_fixtures = _load_agent_fixtures()

    if fixture_filter:
        all_fixtures = [f for f in all_fixtures if fixture_filter in f.stem]
        if not all_fixtures:
            print(f"No agent fixtures found matching '{fixture_filter}'")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  MosAIc Agent Eval Runner — {len(all_fixtures)} fixture(s)")
    print(f"  Prompt version: {prompt_version}")
    print(f"{'='*60}")

    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    results = []

    for fixture_path in all_fixtures:
        result = run_fixture(fixture_path, prompt_version=prompt_version, run_llm=run_llm)
        results.append(result)

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  AGENT RESULTS SUMMARY  (prompt={prompt_version})")
    print(f"{'='*60}")
    print(f"  {'Fixture':<32} {'Valid':>6} {'Schema':>7} {'SQLCorr':>8} {'Judge':>7} {'Errors':>7}")
    print(f"  {'─'*32} {'─'*6} {'─'*7} {'─'*8} {'─'*7} {'─'*7}")

    for r in results:
        sl = r.get("sql_layer", {})
        je = r.get("judge_eval", {})
        valid = sl.get("sql_validity")
        schema = sl.get("schema_adherence")
        corr = sl.get("sql_correctness")
        overall = je.get("overall")
        errs = len(r.get("errors", []))

        v_str = "✅" if valid else ("❌" if valid is not None else "—")
        s_str = "✅" if schema else ("❌" if schema is not None else "—")
        c_str = f"{corr:.2f}" if isinstance(corr, float) else "—"
        j_str = f"{overall:.2f}" if isinstance(overall, float) else "—"

        print(f"  {r['fixture_id']:<32} {v_str:>6} {s_str:>7} {c_str:>8} {j_str:>7} {errs:>7}")

    # ── Save results ──────────────────────────────────────────────────────────
    results_path = RESULTS_DIR / f"agent_eval_{prompt_version}_{run_id}.json"
    results_path.write_text(json.dumps({
        "run_id": run_id,
        "prompt_version": prompt_version,
        "run_at": datetime.utcnow().isoformat() + "Z",
        "fixtures": results,
    }, indent=2, default=str))
    print(f"\n  Results saved: {results_path}")

    if save_baseline:
        from evals.runners.agent_regression import save_agent_baseline
        save_agent_baseline(results)
        print(f"  Agent baseline updated.")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MosAIc Agent Eval Runner")
    parser.add_argument("--fixture", default=None, help="Run only fixtures matching this name")
    parser.add_argument("--prompt-version", default="v1", help="sql_gen/sql_interpret prompt version: v1, v2 (default: v1)")
    parser.add_argument("--save-baseline", action="store_true", help="Save scores as new agent baseline")
    parser.add_argument("--no-llm", action="store_true", help="Skip agent calls entirely (smoke test only)")
    args = parser.parse_args()

    run_all(
        fixture_filter=args.fixture,
        prompt_version=args.prompt_version,
        save_baseline=args.save_baseline,
        run_llm=not args.no_llm,
    )
