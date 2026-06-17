"""
Agent Regression Checker
Compares current agent eval scores against the saved agent baseline.
Separate baseline file from the report pipeline's regression.py.

Usage:
  from evals.runners.agent_regression import save_agent_baseline, check_agent_regression
  python evals/runners/agent_regression.py evals/results/agent_eval_v2_<timestamp>.json
"""

import sys
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_BASELINE_FILE = ROOT / "evals" / "baselines" / "agent_baseline_scores.json"

REGRESSION_THRESHOLD = 0.05  # 5pp drop fails, same convention as report pipeline


def _bool_to_score(b) -> float:
    """sql_validity / schema_adherence are booleans — treat True=1.0, False=0.0 for trend tracking."""
    if b is None:
        return None
    return 1.0 if b else 0.0


def save_agent_baseline(results: list):
    baseline = {
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "scores": {},
    }
    for r in results:
        fid = r["fixture_id"]
        sl = r.get("sql_layer", {})
        je = r.get("judge_eval", {})
        baseline["scores"][fid] = {
            "sql_validity": _bool_to_score(sl.get("sql_validity")),
            "schema_adherence": _bool_to_score(sl.get("schema_adherence")),
            "sql_correctness": sl.get("sql_correctness"),
            "judge_overall": je.get("overall"),
            "answer_faithfulness": je.get("answer_faithfulness"),
            "report_grounding": je.get("report_grounding"),
            "tone_directness": je.get("tone_directness"),
            "specificity": je.get("specificity"),
            "refusal_correctness": je.get("refusal_correctness"),
        }

    AGENT_BASELINE_FILE.parent.mkdir(exist_ok=True)
    AGENT_BASELINE_FILE.write_text(json.dumps(baseline, indent=2))
    print(f"[Agent Regression] Baseline saved to {AGENT_BASELINE_FILE}")


def check_agent_regression(results: list) -> bool:
    if not AGENT_BASELINE_FILE.exists():
        print("[Agent Regression] No baseline found — run with --save-baseline first.")
        return True

    baseline = json.loads(AGENT_BASELINE_FILE.read_text())
    baseline_scores = baseline.get("scores", {})

    print(f"\n{'='*60}")
    print(f"  AGENT REGRESSION CHECK  (threshold: >{REGRESSION_THRESHOLD:.0%} drop = fail)")
    print(f"  Baseline from: {baseline.get('saved_at', 'unknown')}")
    print(f"{'='*60}")

    regressions = []
    all_pass = True

    for result in results:
        fid = result["fixture_id"]
        base = baseline_scores.get(fid)
        if not base:
            print(f"  [{fid}] No baseline entry — skipping")
            continue

        sl = result.get("sql_layer", {})
        je = result.get("judge_eval", {})

        checks = [
            ("sql_validity", _bool_to_score(sl.get("sql_validity")), base.get("sql_validity")),
            ("schema_adherence", _bool_to_score(sl.get("schema_adherence")), base.get("schema_adherence")),
            ("sql_correctness", sl.get("sql_correctness"), base.get("sql_correctness")),
            ("judge_overall", je.get("overall"), base.get("judge_overall")),
            ("answer_faithfulness", je.get("answer_faithfulness"), base.get("answer_faithfulness")),
            ("report_grounding", je.get("report_grounding"), base.get("report_grounding")),
            ("tone_directness", je.get("tone_directness"), base.get("tone_directness")),
            ("specificity", je.get("specificity"), base.get("specificity")),
            ("refusal_correctness", je.get("refusal_correctness"), base.get("refusal_correctness")),
        ]

        fixture_regressions = []
        for metric, current, baseline_val in checks:
            if current is None or baseline_val is None:
                continue
            drop = baseline_val - current
            if drop > REGRESSION_THRESHOLD:
                fixture_regressions.append({
                    "metric": metric,
                    "baseline": baseline_val,
                    "current": current,
                    "drop": drop,
                })

        status = "✅ PASS" if not fixture_regressions else "❌ FAIL"
        print(f"\n  {fid} [{result.get('difficulty', '?')}] — {status}")

        if fixture_regressions:
            all_pass = False
            for reg in fixture_regressions:
                print(f"    ↓ {reg['metric']}: {reg['baseline']:.2f} → {reg['current']:.2f}  (drop: {reg['drop']:.2f})")
            regressions.extend(fixture_regressions)
        else:
            print(f"    All metrics within threshold.")

    print(f"\n{'='*60}")
    if all_pass:
        print(f"  ✅  All agent fixtures PASSED regression check.")
    else:
        print(f"  ❌  {len(regressions)} regression(s) detected. Review prompt changes.")
    print(f"{'='*60}\n")

    return all_pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evals/runners/agent_regression.py <results_file.json>")
        sys.exit(1)

    results_file = Path(sys.argv[1])
    if not results_file.exists():
        print(f"Results file not found: {results_file}")
        sys.exit(1)

    data = json.loads(results_file.read_text())
    results = data.get("fixtures", [])
    passed = check_agent_regression(results)
    sys.exit(0 if passed else 1)
