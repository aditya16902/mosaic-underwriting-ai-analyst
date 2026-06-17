"""
Regression Checker
"""

import sys
import json
from pathlib import Path
from datetime import datetime

ROOT          = Path(__file__).resolve().parent.parent.parent
BASELINE_FILE = ROOT / "evals" / "baselines" / "baseline_scores.json"

REGRESSION_THRESHOLD = 0.05


def save_baseline(results: list):
    baseline = {
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "scores":   {},
    }
    for r in results:
        fid = r["fixture_id"]
        baseline["scores"][fid] = {
            "pipeline_signal_recall": r["pipeline"].get("signal_recall"),
            "llm1_overall":           r["llm1_eval"].get("overall"),
            "llm1_signal_recall":     r["llm1_eval"].get("signal_recall"),
            "llm1_ranking":           r["llm1_eval"].get("ranking_correctness"),
            "llm1_faithfulness":      r["llm1_eval"].get("rationale_faithful"),
            "llm2_overall":           r["llm2_eval"].get("overall"),
            "llm2_signal_accuracy":   r["llm2_eval"].get("signal_accuracy"),
            "llm2_faithfulness":      r["llm2_eval"].get("number_faithfulness"),
            "llm2_tone":              r["llm2_eval"].get("tone_directness"),
        }

    BASELINE_FILE.parent.mkdir(exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(baseline, indent=2))
    print(f"[Regression] Baseline saved to {BASELINE_FILE}")


def check_regression(results: list) -> bool:
    if not BASELINE_FILE.exists():
        print("[Regression] No baseline found — run with --save-baseline first.")
        return True

    baseline        = json.loads(BASELINE_FILE.read_text())
    baseline_scores = baseline.get("scores", {})

    print(f"\n{'='*60}")
    print(f"  REGRESSION CHECK  (threshold: >{REGRESSION_THRESHOLD:.0%} drop = fail)")
    print(f"  Baseline from: {baseline.get('saved_at', 'unknown')}")
    print(f"{'='*60}")

    regressions = []
    all_pass    = True

    for result in results:
        fid  = result["fixture_id"]
        base = baseline_scores.get(fid)
        if not base:
            print(f"  [{fid}] No baseline entry — skipping")
            continue

        checks = [
            ("pipeline_signal_recall", result["pipeline"].get("signal_recall"),           base.get("pipeline_signal_recall")),
            ("llm1_overall",           result["llm1_eval"].get("overall"),                base.get("llm1_overall")),
            ("llm1_ranking",           result["llm1_eval"].get("ranking_correctness"),    base.get("llm1_ranking")),
            ("llm1_faithfulness",      result["llm1_eval"].get("rationale_faithful"),     base.get("llm1_faithfulness")),
            ("llm2_overall",           result["llm2_eval"].get("overall"),                base.get("llm2_overall")),
            ("llm2_signal_accuracy",   result["llm2_eval"].get("signal_accuracy"),        base.get("llm2_signal_accuracy")),
            ("llm2_faithfulness",      result["llm2_eval"].get("number_faithfulness"),    base.get("llm2_faithfulness")),
            ("llm2_tone",              result["llm2_eval"].get("tone_directness"),        base.get("llm2_tone")),
        ]

        fixture_regressions = []
        for metric, current, baseline_val in checks:
            if current is None or baseline_val is None:
                continue
            drop = baseline_val - current
            if drop > REGRESSION_THRESHOLD:
                fixture_regressions.append({
                    "metric":   metric,
                    "baseline": baseline_val,
                    "current":  current,
                    "drop":     drop,
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
        print(f"  ✅  All fixtures PASSED regression check.")
    else:
        print(f"  ❌  {len(regressions)} regression(s) detected. Review prompt changes.")
    print(f"{'='*60}\n")

    return all_pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evals/runners/regression.py <results_file.json>")
        sys.exit(1)

    results_file = Path(sys.argv[1])
    if not results_file.exists():
        print(f"Results file not found: {results_file}")
        sys.exit(1)

    data    = json.loads(results_file.read_text())
    results = data.get("fixtures", [])
    passed  = check_regression(results)
    sys.exit(0 if passed else 1)
