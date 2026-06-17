"""
Agent Judge — Evaluates Text-to-SQL agent output on two layers:

  SQL Generation layer (mostly deterministic, see sql_comparator.py):
    sql_validity      — did it execute without error
    sql_correctness   — does it match the reference query's data (loose compare)
    schema_adherence  — no hallucinated columns/tables

  Interpretation layer (LLM judge):
    answer_faithfulness — every number in the answer traceable to the SQL result
    report_grounding    — correctly connects to report findings when relevant
    tone_directness      — no hedging
    specificity          — actual figures, not vague language
    refusal_correctness — for adversarial fixtures, did it correctly decline/clarify
                           rather than fabricate
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


JUDGE_SYSTEM_PROMPT = """You are a strict evaluation judge for a Text-to-SQL agent that answers a Chief Underwriting Officer's (CUO) natural language questions about an insurance underwriting database.

You will be given:
1. GROUND TRUTH: expectations for this question (must-contain/must-not-contain phrases, whether report grounding is expected, whether the agent should refuse/clarify)
2. QUESTION: what the CUO asked
3. REPORT CONTEXT: what the latest automated weekly report already concluded
4. SQL EXECUTED: the query the agent ran
5. SQL RESULT: the data returned
6. AGENT ANSWER: the natural-language answer the agent produced

Score on five dimensions. Be strict. Return ONLY a valid JSON object:

{
  "answer_faithfulness": <float 0-1>,
  "answer_faithfulness_notes": "<are numbers in the answer traceable to the SQL result? list any fabricated figures>",
  "report_grounding": <float 0-1>,
  "report_grounding_notes": "<if grounding was expected, did the answer explicitly connect to report findings? if not expected, score 1.0>",
  "tone_directness": <float 0-1>,
  "tone_directness_notes": "<list hedging phrases found: may, might, could potentially, it appears, it seems, suggests, pretty, kind of>",
  "specificity": <float 0-1>,
  "specificity_notes": "<does it use actual figures, or vague qualitative language like 'pretty high', 'not great'?>",
  "refusal_correctness": <float 0-1>,
  "refusal_correctness_notes": "<if should_refuse is true: did the agent correctly avoid fabricating an answer (e.g. state data isn't available)? if should_refuse is false, score 1.0 automatically>",
  "overall": <float 0-1>,
  "overall_notes": "<2 sentence summary>"
}

SCORING RULES:
- answer_faithfulness: pick 3-5 numbers from the answer. Score = (traceable to SQL result) / (checked). If should_refuse=true and the answer correctly contains no fabricated numbers, score 1.0.
- report_grounding: if report_grounding_expected=true, does the answer explicitly reference the report's existing concern/opportunity (not just restate raw numbers)? If report_grounding_expected=false, score 1.0 automatically regardless of content.
- tone_directness: start 1.0, subtract 0.15 per hedging or filler phrase found. Floor 0.0.
- specificity: 1.0=concrete figures throughout, 0.7=mostly specific, 0.4=frequently vague, 0.1=almost entirely qualitative ("pretty", "not great", "looking good").
- refusal_correctness: if should_refuse=true, score 1.0 only if the agent clearly avoided fabricating the impossible figure/column (e.g. stated data unavailable, or answered an adjacent answerable question without inventing the missing piece). Score 0.0 if it confidently fabricated a number or column that doesn't exist. If should_refuse=false, always score 1.0.
- overall: (answer_faithfulness*0.25) + (report_grounding*0.20) + (tone_directness*0.20) + (specificity*0.15) + (refusal_correctness*0.20)
"""


def evaluate_agent_answer(
    ground_truth: dict,
    question: str,
    report_context: str,
    sql: str,
    sql_result: dict,
    answer: str,
) -> dict:
    """Run LLM-as-judge evaluation on the agent's interpretation layer."""
    client = OpenAI(api_key=LLM_CONFIG["openai_api_key"])

    result_slim = {
        "success": sql_result.get("success") if sql_result else False,
        "row_count": sql_result.get("row_count") if sql_result else 0,
        "columns": sql_result.get("columns") if sql_result else [],
        "rows": (sql_result.get("rows", [])[:10] if sql_result else []),
        "error": sql_result.get("error") if sql_result else None,
    }

    user_message = f"""## GROUND TRUTH
```json
{json.dumps({
    "answer_must_contain": ground_truth.get("answer_must_contain", []),
    "answer_must_not_contain": ground_truth.get("answer_must_not_contain", []),
    "report_grounding_expected": ground_truth.get("report_grounding_expected", False),
    "report_grounding_note": ground_truth.get("report_grounding_note", ""),
    "should_refuse": ground_truth.get("should_refuse", False),
    "eval_notes": ground_truth.get("eval_notes", ""),
}, indent=2)}
```

## QUESTION
{question}

## REPORT CONTEXT
{report_context}

## SQL EXECUTED
```sql
{sql}
```

## SQL RESULT
```json
{_safe_json(result_slim)}
```

## AGENT ANSWER
{answer}

Now score strictly. Return only the JSON object."""

    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0.0,
        max_tokens=1200,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
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

    scores["judge_model"] = JUDGE_MODEL
    scores["judge_tokens"] = {
        "prompt": response.usage.prompt_tokens,
        "completion": response.usage.completion_tokens,
    }
    return scores
