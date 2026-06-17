"""
Eval Runner
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

from backend.pipeline.ingestor    import merge_tables, compute_metrics
from backend.pipeline.signals     import detect_all_signals
from backend.pipeline.enrichment  import enrich_all
from backend.pipeline.anomalies   import detect_all_anomalies
from backend.pipeline.prioritiser import build_payload
from evals.runners.fixture_loader import load_fixture_data


def _load_all_fixtures() -> list:
    return sorted(FIXTURES_DIR.glob("*.json"))


def _run_pipeline_on_fixture(fixture: dict) -> tuple:
    raw  = load_fixture_data(fixture)
    df   = merge_tables(raw)
    df   = compute_metrics(df)
    signals   = detect_all_signals(df)
    enriched  = enrich_all(df, signals)
    anomalies = detect_all_anomalies(df)
    payload   = build_payload(df=df, enriched_signals=enriched,
                               anomalies=anomalies, week_start=None, week_end=None)
    return df, payload


def _score_pipeline_signals(fixture: dict, payload: dict) -> dict:
    gt      = fixture["ground_truth"]
    expected = gt.get("expected_signals", {})
    sig_id_map = {
        "S1_structural_underperformance": "S1",
        "S2_hit_rate_collapse":           "S2",
        "S3_loss_ratio_deterioration":    "S3",
        "S4_profitable_outperformance":   "S4",
    }

    total_expected, total_correct = 0, 0
    results = {}

    for sig_key, expected_lobs in expected.items():
        sig_id = sig_id_map.get(sig_key, "")
        detected_lobs = [
            c["lob"] for c in payload.get("all_concerns", []) + payload.get("all_opportunities", [])
            if c.get("signal_id") == sig_id
        ]
        expected_set = set(expected_lobs)
        detected_set = set(detected_lobs)
        correct = expected_set & detected_set
        missed  = expected_set - detected_set
        extra   = detected_set - expected_set

        total_expected += len(expected_set)
        total_correct  += len(correct)

        results[sig_key] = {
            "expected": list(expected_set),
            "detected": list(detected_set),
            "correct":  list(correct),
            "missed":   list(missed),
            "extra":    list(extra),
        }

    signal_recall = total_correct / total_expected if total_expected > 0 else 1.0
    return {"per_signal": results, "signal_recall": round(signal_recall, 3)}


def run_fixture(fixture_path: Path, run_llm: bool = True, prompt_version: str = "v1") -> dict:
    fixture    = json.loads(fixture_path.read_text())
    fixture_id = fixture["fixture_id"]
    difficulty = fixture.get("difficulty", "unknown")

    print(f"\n  {'─'*50}")
    print(f"  Fixture: {fixture_id}  [{difficulty}]  prompt={prompt_version}")
    print(f"  {'─'*50}")

    result = {
        "fixture_id":     fixture_id,
        "difficulty":     difficulty,
        "prompt_version": prompt_version,
        "run_at":         datetime.utcnow().isoformat() + "Z",
        "pipeline":       {},
        "llm1_eval":      {},
        "llm2_eval":      {},
        "errors":         [],
    }

    # ── Pipeline ──────────────────────────────────────────────────────────────
    try:
        print(f"  [Pipeline] Running layers 1-4...")
        df, payload = _run_pipeline_on_fixture(fixture)
        pipeline_scores = _score_pipeline_signals(fixture, payload)
        result["pipeline"] = {
            "signal_recall":     pipeline_scores["signal_recall"],
            "per_signal":        pipeline_scores["per_signal"],
            "concern_count":     len(payload.get("all_concerns", [])),
            "opportunity_count": len(payload.get("all_opportunities", [])),
        }
        print(f"  [Pipeline] Signal recall: {pipeline_scores['signal_recall']:.2f}")
        for sig, detail in pipeline_scores["per_signal"].items():
            status = "✅" if not detail["missed"] and not detail["extra"] else "⚠️ "
            print(f"    {status} {sig}: expected={detail['expected']} detected={detail['detected']}"
                  + (f" MISSED={detail['missed']}" if detail["missed"] else "")
                  + (f" EXTRA={detail['extra']}"   if detail["extra"]  else ""))
    except Exception as e:
        result["errors"].append(f"Pipeline error: {e}")
        print(f"  [Pipeline] ERROR: {e}")
        import traceback; traceback.print_exc()
        return result

    if not run_llm:
        print(f"  [LLM] Skipped (--no-llm)")
        return result

    # ── LLM Chain ─────────────────────────────────────────────────────────────
    try:
        from backend.llm.chain import run_llm_chain
        print(f"  [LLM Chain] Running with prompt {prompt_version}...")
        llm_chain      = run_llm_chain(payload, prompt_version=prompt_version)
        llm1_parsed    = llm_chain.get("llm1", {}).get("parsed", {})
        narrative_html = llm_chain.get("narrative_html", "")
    except Exception as e:
        result["errors"].append(f"LLM chain error: {e}")
        print(f"  [LLM Chain] ERROR: {e}")
        import traceback; traceback.print_exc()
        return result

    # ── LLM1 Judge ────────────────────────────────────────────────────────────
    try:
        from evals.judges.llm1_judge import evaluate_llm1
        print(f"  [LLM1 Judge] Evaluating prioritisation...")
        llm1_scores = evaluate_llm1(
            ground_truth=fixture["ground_truth"],
            llm1_parsed=llm1_parsed,
            payload=payload,
        )
        result["llm1_eval"] = llm1_scores
        print(f"  [LLM1 Judge] Overall: {llm1_scores.get('overall', 0):.2f}  "
              f"| signal_recall={llm1_scores.get('signal_recall', 'N/A')}  "
              f"| ranking={llm1_scores.get('ranking_correctness', 'N/A')}  "
              f"| faithful={llm1_scores.get('rationale_faithful', 'N/A')}")
    except Exception as e:
        result["errors"].append(f"LLM1 judge error: {e}")
        print(f"  [LLM1 Judge] ERROR: {e}")
        import traceback; traceback.print_exc()

    # ── LLM2 Judge ────────────────────────────────────────────────────────────
    try:
        from evals.judges.llm2_judge import evaluate_llm2
        print(f"  [LLM2 Judge] Evaluating narrative...")
        llm2_scores = evaluate_llm2(
            ground_truth=fixture["ground_truth"],
            narrative_html=narrative_html,
            payload=payload,
        )
        result["llm2_eval"] = llm2_scores
        print(f"  [LLM2 Judge] Overall: {llm2_scores.get('overall', 0):.2f}  "
              f"| signal_accuracy={llm2_scores.get('signal_accuracy', 'N/A')}  "
              f"| faithfulness={llm2_scores.get('number_faithfulness', 'N/A')}  "
              f"| tone={llm2_scores.get('tone_directness', 'N/A')}")
    except Exception as e:
        result["errors"].append(f"LLM2 judge error: {e}")
        print(f"  [LLM2 Judge] ERROR: {e}")
        import traceback; traceback.print_exc()

    return result


def run_all(fixture_filter: Optional[str], run_llm: bool, save_baseline: bool, prompt_version: str):
    all_fixtures = _load_all_fixtures()

    if fixture_filter:
        all_fixtures = [f for f in all_fixtures if fixture_filter in f.stem]
        if not all_fixtures:
            print(f"No fixtures found matching '{fixture_filter}'")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  MosAIc Eval Runner — {len(all_fixtures)} fixture(s)")
    print(f"  LLM calls:      {'YES' if run_llm else 'NO (--no-llm)'}")
    print(f"  Prompt version: {prompt_version}")
    print(f"{'='*60}")

    run_id  = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    results = []

    for fixture_path in all_fixtures:
        result = run_fixture(fixture_path, run_llm=run_llm, prompt_version=prompt_version)
        results.append(result)

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY  (prompt={prompt_version})")
    print(f"{'='*60}")
    print(f"  {'Fixture':<30} {'Pipeline':>10} {'LLM1':>8} {'LLM2':>8} {'Errors':>8}")
    print(f"  {'─'*30} {'─'*10} {'─'*8} {'─'*8} {'─'*8}")

    for r in results:
        ps = r["pipeline"].get("signal_recall", "N/A")
        l1 = r["llm1_eval"].get("overall",      "N/A")
        l2 = r["llm2_eval"].get("overall",      "N/A")
        e  = len(r.get("errors", []))
        print(f"  {r['fixture_id']:<30} "
              f"{f'{ps:.2f}' if isinstance(ps, float) else ps:>10} "
              f"{f'{l1:.2f}' if isinstance(l1, float) else l1:>8} "
              f"{f'{l2:.2f}' if isinstance(l2, float) else l2:>8} "
              f"{e:>8}")

    # ── Save results ──────────────────────────────────────────────────────────
    results_path = RESULTS_DIR / f"eval_{prompt_version}_{run_id}.json"
    results_path.write_text(json.dumps({
        "run_id":         run_id,
        "prompt_version": prompt_version,
        "run_at":         datetime.utcnow().isoformat() + "Z",
        "fixtures":       results,
    }, indent=2, default=str))
    print(f"\n  Results saved: {results_path}")

    if save_baseline:
        from evals.runners.regression import save_baseline as _save
        _save(results)
        print(f"  Baseline updated.")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MosAIc Eval Runner")
    parser.add_argument("--fixture",        default=None,  help="Run only fixtures matching this name")
    parser.add_argument("--no-llm",         action="store_true", help="Skip LLM calls and judge evaluation")
    parser.add_argument("--save-baseline",  action="store_true", help="Save scores as new baseline")
    parser.add_argument("--prompt-version", default="v1",  help="Prompt version to use: v1, v2, ... (default: v1)")
    args = parser.parse_args()

    run_all(
        fixture_filter=args.fixture,
        run_llm=not args.no_llm,
        save_baseline=args.save_baseline,
        prompt_version=args.prompt_version,
    )
