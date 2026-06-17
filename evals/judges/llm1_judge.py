"""
LLM1 Judge — Evaluates prioritisation correctness and rationale faithfulness.
"""

import json
import numpy as np
from openai import OpenAI
from backend.config import LLM_CONFIG

JUDGE_MODEL = "gpt-4o"


def _safe_json(obj) -> str:
    """Serialise payload safely — converts numpy types to native Python."""
    def _convert(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(f"Object of type {type(o)} is not JSON serializable")
    return json.dumps(obj, indent=2, default=_convert)


JUDGE_SYSTEM_PROMPT = """You are a strict evaluation judge for an insurance analytics AI system.

You will be given:
1. GROUND TRUTH: the expected signals, top concerns, and opportunity for a test case
2. LLM1 OUTPUT: the actual prioritisation produced by the system under evaluation
3. PAYLOAD SUMMARY: key metrics from the data payload (for faithfulness checking)

Your job is to score the LLM1 output on five dimensions. Be strict and precise.

Return ONLY a valid JSON object with this exact structure:
{
  "signal_recall": <float 0-1>,
  "signal_recall_notes": "<which expected signals were missed, if any>",
  "signal_precision": <float 0-1>,
  "signal_precision_notes": "<which hallucinated signals appeared, if any>",
  "ranking_correctness": <float 0-1>,
  "ranking_correctness_notes": "<was rank 1 correct? rank 2? rank 3?>",
  "opportunity_correct": <float 0 or 1>,
  "opportunity_notes": "<was the opportunity correctly identified or correctly absent?>",
  "rationale_faithful": <float 0-1>,
  "rationale_faithful_notes": "<do the rationales use real numbers from payload? list any hallucinated figures>",
  "overall": <float 0-1>,
  "overall_notes": "<1-2 sentence summary of the evaluation>"
}

SCORING RULES:
- signal_recall: (signals correctly identified) / (total expected signals). If no signals expected and none returned = 1.0
- signal_precision: 1.0 - (hallucinated signals / total returned). Hallucinated = signal not in ground truth expected_signals
- ranking_correctness: Rank 1 correct = 0.5, Rank 2 correct = 0.3, Rank 3 correct = 0.2. Sum what's correct. If fewer than 3 concerns expected, scale accordingly.
- opportunity_correct: 1.0 if opportunity matches expected (lob + signal_id), 0.0 if wrong or present when null expected, 1.0 if both null
- rationale_faithful: check each one_line_rationale for numbers (£ figures, percentages). If numbers appear in payload = faithful. Penalise 0.2 per hallucinated figure.
- overall: (signal_recall * 0.25) + (signal_precision * 0.20) + (ranking_correctness * 0.25) + (opportunity_correct * 0.15) + (rationale_faithful * 0.15)
"""


def evaluate_llm1(ground_truth: dict, llm1_parsed: dict, payload: dict) -> dict:
    client = OpenAI(api_key=LLM_CONFIG["openai_api_key"])

    # Slim down payload to just what's needed for faithfulness checking
    payload_summary = {
        "portfolio_summary": payload.get("portfolio_summary", {}),
        "all_concerns": [{k: v for k, v in c.items() if k in [
            "signal_id", "lob", "gwp_at_risk", "ytd_actual_gwp", "ytd_plan_gwp",
            "mean_gwp_ratio", "open_pipeline_gwp", "est_underwriting_loss",
            "final_loss_ratio", "gwp_surplus", "impact_score",
        ]} for c in payload.get("all_concerns", [])],
        "all_opportunities": [{k: v for k, v in o.items() if k in [
            "signal_id", "lob", "gwp_surplus", "final_loss_ratio", "health_verdict",
        ]} for o in payload.get("all_opportunities", [])],
    }

    user_message = f"""## GROUND TRUTH
```json
{json.dumps(ground_truth, indent=2)}
```

## LLM1 OUTPUT (system under evaluation)
```json
{json.dumps(llm1_parsed, indent=2)}
```

## PAYLOAD SUMMARY (for faithfulness verification)
```json
{_safe_json(payload_summary)}
```

Now score the LLM1 output strictly against the ground truth. Return only the JSON object."""

    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0.0,
        max_tokens=1000,
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
