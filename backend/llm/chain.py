"""
Layer 5 — Two-LLM Chain with Langfuse Observability
"""

import json
import os
import time
import numpy as np
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from openai import OpenAI

def _json_safe(obj) -> str:
    def _convert(o):
        if isinstance(o, np.integer):  return int(o)
        if isinstance(o, np.floating): return float(o)
        if isinstance(o, np.ndarray):  return o.tolist()
        raise TypeError(f"Not serializable: {type(o)}")
    return json.dumps(obj, indent=2, default=_convert)


# ── Langfuse ───────────────────────────────────────────────────────────────────
_LANGFUSE_ENABLED = False
langfuse = None

try:
    from langfuse import Langfuse
    from langfuse.decorators import observe, langfuse_context

    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")

    if pk and sk:
        langfuse = Langfuse()
        _LANGFUSE_ENABLED = True
        print(f"[Langfuse] Initialised (env vars)")
    else:
        print("[Langfuse] Keys not set — tracing disabled.")

except ImportError:
    print("[Langfuse] SDK not installed — tracing disabled.")
except Exception as e:
    print(f"[Langfuse] Init error: {e}")

from backend.config import LLM_CONFIG
from backend.llm.observability import make_session_id

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _prompt_file(role: str, version: str) -> str:
    return f"llm{role}_{'prioritisation' if role == '1' else 'narrative'}_{version}.txt"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _openai_client() -> OpenAI:
    key = LLM_CONFIG["openai_api_key"]
    if not key:
        raise ValueError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=key)


# ── Observed functions ─────────────────────────────────────────────────────────

if _LANGFUSE_ENABLED:

    @observe(name="llm1_prioritisation")
    def _run_llm1_observed(payload_json: str, prompt_version: str,
                            system_prompt: str) -> tuple:
        user = (
            "Here is the full underwriting performance payload. "
            "Analyse all detected signals and return your prioritisation JSON.\n\n"
            f"```json\n{payload_json}\n```"
        )
        resp = _openai_client().chat.completions.create(
            model=LLM_CONFIG["llm1_model"],
            temperature=LLM_CONFIG["temperature"],
            max_tokens=LLM_CONFIG["llm1_max_tokens"],
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user",   "content": user}],
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
            raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            parsed = {"error": str(e), "raw_output": raw}

        langfuse_context.update_current_observation(
            input=user[:500],
            output={"top_concerns":    parsed.get("top_concerns", []),
                    "top_opportunity": parsed.get("top_opportunity", {})},
            metadata={"model": LLM_CONFIG["llm1_model"],
                      "prompt_version": prompt_version},
            usage={"input":  resp.usage.prompt_tokens,
                   "output": resp.usage.completion_tokens,
                   "total":  resp.usage.total_tokens,
                   "unit":   "TOKENS"},
        )
        return raw, parsed, resp.usage

    @observe(name="llm2_narrative")
    def _run_llm2_observed(payload_json: str, llm1_json: str,
                            prompt_version: str, system_prompt: str) -> tuple:
        user = (
            "You are writing the weekly CUO performance briefing for Mosaic Insurance.\n\n"
            f"## FULL ANALYTICS PAYLOAD\n```json\n{payload_json}\n```\n\n"
            f"## PEER LLM PRIORITISATION\n```json\n{llm1_json}\n```\n\n"
            "Produce the McKinsey-style CUO executive briefing as complete HTML. "
            "Return ONLY the HTML — no markdown fences."
        )
        resp = _openai_client().chat.completions.create(
            model=LLM_CONFIG["llm2_model"],
            temperature=LLM_CONFIG["temperature"],
            max_tokens=LLM_CONFIG["llm2_max_tokens"],
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user",   "content": user}],
        )
        html = resp.choices[0].message.content.strip()
        if html.startswith("```"):
            parts = html.split("```")
            html  = parts[1] if len(parts) > 1 else html
            if html.startswith("html"): html = html[4:].strip()

        langfuse_context.update_current_observation(
            input=llm1_json[:300],
            output={"html_length": len(html), "html_preview": html[:200]},
            metadata={"model": LLM_CONFIG["llm2_model"],
                      "prompt_version": prompt_version},
            usage={"input":  resp.usage.prompt_tokens,
                   "output": resp.usage.completion_tokens,
                   "total":  resp.usage.total_tokens,
                   "unit":   "TOKENS"},
        )
        return html, resp.usage

    @observe(name="weekly_performance_analyst")
    def _run_chain_observed(payload: dict, run_id: Optional[str],
                             prompt_version: str) -> dict:
        ps          = payload.get("portfolio_summary", {})
        week_ending = ps.get("report_week")
        session_id  = make_session_id(week_ending)

        langfuse_context.update_current_trace(
            session_id=session_id,
            input={"report_week":   week_ending,
                   "concern_count": len(payload.get("all_concerns", []))},
            metadata={"mosaic_run_id":  run_id,
                      "prompt_version": prompt_version},
            tags=["analytics-pipeline", f"prompt_{prompt_version}"],
        )

        payload_json = _json_safe(payload)

        pf1  = _prompt_file("1", prompt_version)
        sys1 = _load_prompt(pf1)
        print(f"[LLM1] Running ({LLM_CONFIG['llm1_model']}) — prompt {prompt_version}...")
        raw1, parsed1, usage1 = _run_llm1_observed(payload_json, prompt_version, sys1)
        if "error" in parsed1:
            print(f"[LLM1] WARNING: parse error — {parsed1['error']}")

        pf2       = _prompt_file("2", prompt_version)
        sys2      = _load_prompt(pf2)
        llm1_json = json.dumps(parsed1, indent=2, default=str)
        print(f"[LLM2] Running ({LLM_CONFIG['llm2_model']}) — prompt {prompt_version}...")
        html2, usage2 = _run_llm2_observed(payload_json, llm1_json, prompt_version, sys2)
        print("[LLM Chain] Complete.")

        langfuse_context.update_current_trace(
            output={"top_concerns":    parsed1.get("top_concerns", []),
                    "top_opportunity": parsed1.get("top_opportunity", {}),
                    "analyst_notes":   parsed1.get("analyst_notes", "")},
            metadata={"total_tokens": usage1.total_tokens + usage2.total_tokens},
        )

        # NOTE: Do NOT flush here — the @observe decorator hasn't finished
        # writing the trace yet at this point. Flush must happen AFTER the
        # decorated function returns, which run_llm_chain() handles below.

        return _build_result(pf1, sys1, raw1, parsed1, usage1,
                             pf2, sys2, html2, usage2,
                             prompt_version, session_id)


def _build_result(pf1, sys1, raw1, parsed1, usage1,
                  pf2, sys2, html2, usage2,
                  prompt_version, session_id) -> dict:
    return {
        "llm1": {"model": LLM_CONFIG["llm1_model"], "prompt_file": pf1,
                 "prompt_version": prompt_version, "prompt_text": sys1,
                 "raw_output": raw1, "parsed": parsed1,
                 "usage": {"prompt_tokens":     usage1.prompt_tokens,
                           "completion_tokens": usage1.completion_tokens,
                           "total_tokens":      usage1.total_tokens}},
        "llm2": {"model": LLM_CONFIG["llm2_model"], "prompt_file": pf2,
                 "prompt_version": prompt_version, "prompt_text": sys2,
                 "html": html2,
                 "usage": {"prompt_tokens":     usage2.prompt_tokens,
                           "completion_tokens": usage2.completion_tokens,
                           "total_tokens":      usage2.total_tokens}},
        "prompt_version":  prompt_version,
        "session_id":      session_id,
        "top_concerns":    parsed1.get("top_concerns", []),
        "top_opportunity": parsed1.get("top_opportunity", {}),
        "analyst_notes":   parsed1.get("analyst_notes", ""),
        "narrative_html":  html2,
    }


def run_llm1(payload: dict, prompt_version: str = "v1", trace=None) -> dict:
    """Standalone LLM1 — used by eval runner (no tracing)."""
    pf    = _prompt_file("1", prompt_version)
    sys_p = _load_prompt(pf)
    user  = (
        "Here is the full underwriting performance payload. "
        "Analyse all detected signals and return your prioritisation JSON.\n\n"
        f"```json\n{_json_safe(payload)}\n```"
    )
    resp = _openai_client().chat.completions.create(
        model=LLM_CONFIG["llm1_model"], temperature=LLM_CONFIG["temperature"],
        max_tokens=LLM_CONFIG["llm1_max_tokens"],
        messages=[{"role": "system", "content": sys_p},
                  {"role": "user",   "content": user}],
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        parsed = {"error": str(e), "raw_output": raw}
    return {
        "model": LLM_CONFIG["llm1_model"], "prompt_file": pf,
        "prompt_version": prompt_version, "prompt_text": sys_p,
        "raw_output": raw, "parsed": parsed,
        "usage": {"prompt_tokens":     resp.usage.prompt_tokens,
                  "completion_tokens": resp.usage.completion_tokens,
                  "total_tokens":      resp.usage.total_tokens},
    }


def run_llm_chain(
    payload: dict,
    run_id: Optional[str] = None,
    prompt_version: str = "v1",
) -> dict:
    if _LANGFUSE_ENABLED:
        # _run_chain_observed is decorated with @observe.
        # The decorator finalises and buffers the trace AFTER the function returns.
        # We must flush AFTER the call, not inside it.
        result = _run_chain_observed(payload, run_id, prompt_version)

        # Give the decorator's post-execution hook a moment to write to the buffer,
        # then flush the singleton client the decorator uses internally.
        time.sleep(0.5)
        langfuse.flush()
        print(f"[Langfuse] Flushed — session: {result.get('session_id', '')}")
        return result

    # ── Fallback: no tracing ──────────────────────────────────────────────────
    ps           = payload.get("portfolio_summary", {})
    session_id   = make_session_id(ps.get("report_week"))
    payload_json = _json_safe(payload)

    print(f"[LLM1] Running ({LLM_CONFIG['llm1_model']}) — prompt {prompt_version}...")
    llm1 = run_llm1(payload, prompt_version=prompt_version)
    if "error" in llm1.get("parsed", {}):
        print(f"[LLM1] WARNING: parse error")

    pf2   = _prompt_file("2", prompt_version)
    sys2  = _load_prompt(pf2)
    user2 = (
        f"## FULL ANALYTICS PAYLOAD\n```json\n{payload_json}\n```\n\n"
        f"## PEER LLM PRIORITISATION\n```json\n"
        f"{json.dumps(llm1.get('parsed', {}), indent=2, default=str)}\n```\n\n"
        "Return ONLY the HTML."
    )
    print(f"[LLM2] Running ({LLM_CONFIG['llm2_model']}) — prompt {prompt_version}...")
    resp2 = _openai_client().chat.completions.create(
        model=LLM_CONFIG["llm2_model"], temperature=LLM_CONFIG["temperature"],
        max_tokens=LLM_CONFIG["llm2_max_tokens"],
        messages=[{"role": "system", "content": sys2},
                  {"role": "user",   "content": user2}],
    )
    html = resp2.choices[0].message.content.strip()
    if html.startswith("```"):
        parts = html.split("```"); html = parts[1] if len(parts) > 1 else html
        if html.startswith("html"): html = html[4:].strip()
    print("[LLM Chain] Complete.")

    return {
        "llm1": llm1,
        "llm2": {"model": LLM_CONFIG["llm2_model"], "prompt_file": pf2,
                 "prompt_version": prompt_version, "prompt_text": sys2, "html": html,
                 "usage": {"prompt_tokens":     resp2.usage.prompt_tokens,
                           "completion_tokens": resp2.usage.completion_tokens,
                           "total_tokens":      resp2.usage.total_tokens}},
        "prompt_version":  prompt_version,
        "session_id":      session_id,
        "top_concerns":    llm1.get("parsed", {}).get("top_concerns", []),
        "top_opportunity": llm1.get("parsed", {}).get("top_opportunity", {}),
        "analyst_notes":   llm1.get("parsed", {}).get("analyst_notes", ""),
        "narrative_html":  html,
    }
