"""
LLM2 Judge — Evaluates narrative quality.
"""

import json
import numpy as np
from openai import OpenAI
from backend.config import LLM_CONFIG

JUDGE_MODEL = "gpt-4o"


def _safe_json(obj) -> str:
    def _convert(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(f"Object of type {type(o)} is not JSON serializable")
    return json.dumps(obj, indent=2, default=_convert)


JUDGE_SYSTEM_PROMPT = """You are a strict evaluation judge assessing the quality of an AI-generated executive briefing for a Chief Underwriting Officer (CUO) at an insurance company.

You will be given:
1. GROUND TRUTH: expected signal coverage, numbers that must appear, phrases that must not appear
2. NARRATIVE HTML: the actual narrative produced by the system
3. PAYLOAD SUMMARY: the underlying data (for faithfulness checking)

Score on five dimensions. Return ONLY a valid JSON object:

{
  "signal_accuracy": <float 0-1>,
  "signal_accuracy_notes": "<which expected signals are correctly covered, which are missing or misattributed>",
  "number_faithfulness": <float 0-1>,
  "number_faithfulness_notes": "<list up to 3 specific numbers from the narrative and whether they exist in the payload>",
  "tone_directness": <float 0-1>,
  "tone_directness_notes": "<list any hedging phrases found: may, might, could potentially, it appears, it seems, suggests>",
  "specificity": <float 0-1>,
  "specificity_notes": "<are actual figures used, or vague language like significantly without numbers?>",
  "root_cause_coverage": <float 0-1>,
  "root_cause_coverage_notes": "<for S1: does it diagnose losing-to-price vs too-selective? For S4: does it verify loss ratio health?>",
  "overall": <float 0-1>,
  "overall_notes": "<2 sentence summary>"
}

SCORING RULES:
- signal_accuracy: (expected signals correctly covered) / (total expected signals). If no signals expected = 1.0.
- number_faithfulness: pick 3-5 numbers from the narrative. Score = (traceable to payload) / (checked). If no numbers = 0.2.
- tone_directness: start 1.0, subtract 0.15 per hedging phrase. Floor 0.0.
- specificity: 1.0=all figures, 0.7=mostly, 0.4=frequently vague, 0.1=almost no figures.
- root_cause_coverage: 0.5 per correct diagnosis (S1 pricing/selectivity, S4 loss health). If neither expected = 1.0.
- overall: (signal_accuracy*0.30) + (number_faithfulness*0.25) + (tone_directness*0.20) + (specificity*0.15) + (root_cause_coverage*0.10)

Strip HTML tags mentally when reading the narrative.
"""


def evaluate_llm2(ground_truth: dict, narrative_html: str, payload: dict) -> dict:
    client = OpenAI(api_key=LLM_CONFIG["openai_api_key"])

    payload_summary = {
        "portfolio_summary": payload.get("portfolio_summary", {}),
        "lob_snapshot":      payload.get("lob_snapshot", []),
        "all_concerns":      [{k: v for k, v in c.items() if k in [
            "signal_id", "lob", "gwp_at_risk", "ytd_actual_gwp", "ytd_plan_gwp",
            "mean_gwp_ratio", "final_loss_ratio", "est_underwriting_loss",
            "open_pipeline_gwp", "gwp_surplus", "root_cause", "impact_score",
            "recent_avg_decline_rate", "recent_avg_ntu_rate", "recent_avg_pipeline_days",
        ]} for c in payload.get("all_concerns", [])],
        "all_opportunities": [{k: v for k, v in o.items() if k in [
            "signal_id", "lob", "gwp_surplus", "final_loss_ratio",
            "health_verdict", "health_note",
        ]} for o in payload.get("all_opportunities", [])],
    }

    user_message = f"""## GROUND TRUTH
```json
{json.dumps({
    "expected_signals":           ground_truth.get("expected_signals", {}),
    "narrative_must_contain":     ground_truth.get("narrative_must_contain", []),
    "narrative_must_not_contain": ground_truth.get("narrative_must_not_contain", []),
    "numbers_to_verify":          ground_truth.get("numbers_to_verify", []),
    "root_cause_expected":        ground_truth.get("root_cause_expected"),
    "opportunity_health_expected": ground_truth.get("opportunity_health_expected"),
}, indent=2)}
```

## PAYLOAD SUMMARY (for faithfulness checking)
```json
{_safe_json(payload_summary)}
```

## NARRATIVE HTML (system under evaluation)
{narrative_html[:6000]}

Now score strictly. Return only the JSON object."""

    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0.0,
        max_tokens=1200,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        scores = json.loads(raw)
    except json.JSONDecodeError as e:
        scores = {"error": str(e), "raw": raw, "overall": 0.0}

    scores["judge_model"]  = JUDGE_MODEL
    scores["judge_tokens"] = {
        "prompt":     response.usage.prompt_tokens,
        "completion": response.usage.completion_tokens,
    }
    return scores
