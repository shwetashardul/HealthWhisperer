from typing import Any, Dict, List, Optional
import os
import re
import json
from datetime import datetime
from random import randint
from dotenv import load_dotenv

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit not present in some contexts
    st = None  # type: ignore

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None  # type: ignore

from .prompts import (
    SYSTEM_MOTIVATION,
    SYSTEM_NUDGE,
    SYSTEM_PORTIONS,
    SYSTEM_SUMMARY,
)


def get_gemini_api_key() -> Optional[str]:
    load_dotenv(override=False)
    # Prefer Streamlit secrets if available when called from app
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY") if hasattr(st, "secrets") else None
    except Exception:
        secret_key = None

    env_key = os.getenv("GEMINI_API_KEY")
    return str(secret_key) if secret_key else env_key


def _configure_client() -> Optional[str]:
    """Configure the Gemini client if possible; returns the API key if set."""
    api_key = get_gemini_api_key()
    if api_key and genai:
        try:
            genai.configure(api_key=api_key)
        except Exception:
            pass
    return api_key


def _store_debug_text(raw_text: str) -> None:
    if not st:
        return
    try:
        if "debug" not in st.session_state or not isinstance(st.session_state.get("debug"), dict):
            st.session_state["debug"] = {}
        st.session_state["debug"]["last_gemini_text"] = raw_text
    except Exception:
        pass


def _strip_code_fences(text: str) -> str:
    # Remove triple backtick fences, optionally with language specifier
    fenced = re.findall(r"```[a-zA-Z]*\n([\s\S]*?)```", text)
    return fenced[0] if fenced else text


def _best_effort_json(text: str) -> Dict[str, Any]:
    """Extract JSON object from model text. Fallback to {raw_text: ...}."""
    cleaned = _strip_code_fences(text).strip()
    # If it's already valid JSON
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
    except Exception:
        pass
    # Try to slice between first '{' and last '}'
    try:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start : end + 1]
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
            return {"data": parsed}
    except Exception:
        pass
    return {"raw_text": text}


def call_gemini(
    user_prompt: str,
    system_prompt: Optional[str] = None,
    model: str = "gemini-1.5-flash",
    temperature: float = 0.7,
    expect_json: bool = False,
) -> Any:
    """Low-level call to Gemini with optional JSON response handling.

    Returns dict if expect_json=True else string.
    Always stores raw text in st.session_state['debug']['last_gemini_text'].
    """
    api_key = _configure_client()
    generation_config: Dict[str, Any] = {
        "temperature": float(temperature),
    }
    if expect_json:
        generation_config["response_mime_type"] = "application/json"

    if not api_key or not genai:
        raw_text = "[Gemini disabled] Missing API key or client library."
        _store_debug_text(raw_text)
        return {"raw_text": raw_text} if expect_json else raw_text

    try:
        gmodel = genai.GenerativeModel(model_name=model, system_instruction=system_prompt) if system_prompt else genai.GenerativeModel(model_name=model)
        response = gmodel.generate_content(user_prompt, generation_config=generation_config)
        raw_text = getattr(response, "text", None) or ""
    except Exception as exc:  # runtime or API error
        raw_text = f"[Gemini error] {exc}"
    _store_debug_text(raw_text)

    if expect_json:
        return _best_effort_json(raw_text)
    return raw_text


# -----------------------------
# High-level helpers
# -----------------------------


def _rotate_greeting() -> str:
    greetings = [
        "Keep going",
        "You've got this",
        "Onward",
        "Nice progress",
        "Steady and strong",
        "Small steps",
        "One step at a time",
    ]
    try:
        idx = (datetime.utcnow().day + randint(0, 6)) % len(greetings)
    except Exception:
        idx = 0
    return greetings[idx]


def generate_motivational_headline(previous_positives: List[str], first_name: str, goal_hint: Optional[str]) -> str:
    constraint = "Return one short line (<=14 words). No medical claims."
    positives_text = "; ".join(previous_positives[:5]) if previous_positives else ""
    user_prompt = (
        f"Name: {first_name or 'Friend'}\n"
        f"Goal hint: {goal_hint or ''}\n"
        f"Recent positives: {positives_text}\n\n"
        f"{constraint}\n"
    )
    text = call_gemini(user_prompt=user_prompt, system_prompt=SYSTEM_MOTIVATION, expect_json=False)
    line = str(text).strip() if text else ""
    if not line:
        line = f"{_rotate_greeting()}, {first_name or 'Friend'}! Small steps add up."
    # Enforce single line and word count
    line = line.replace("\n", " ").strip()
    if len(line.split()) > 14:
        line = " ".join(line.split()[:14])
    return line


def _normalize_nudge(data: Dict[str, Any]) -> Dict[str, Any]:
    title = str(data.get("title") or "").strip()
    body = str(data.get("body") or "").strip()
    rationale = str(data.get("rationale") or "").strip()
    category = str(data.get("category") or "").strip().lower()
    return {"title": title, "body": body, "rationale": rationale, "category": category}


def _fallback_nudge(context: Dict[str, Any]) -> Dict[str, Any]:
    hint = str((context or {}).get("hint") or "Take a mindful sip of water.")
    return {
        "title": "Quick hydration",
        "body": hint,
        "rationale": "Gentle nudge when context is limited.",
        "category": "hydration",
    }


def suggest_nudge(context_dict: Dict[str, Any]) -> Dict[str, Any]:
    # Respect privacy flag in prompts; the model should consider profile only if share_profile_with_ai=True
    user_prompt = json.dumps(
        {
            "context": context_dict,
            "instructions": {
                "shape": {"title": "str", "body": "str", "rationale": "str", "category": "str"},
                "category_lower": True,
            },
        },
        ensure_ascii=False,
    )
    resp = call_gemini(user_prompt=user_prompt, system_prompt=SYSTEM_NUDGE, expect_json=True)
    data = resp if isinstance(resp, dict) else {"raw_text": str(resp)}
    norm = _normalize_nudge(data)
    if not norm["title"] or not norm["body"]:
        return _fallback_nudge(context_dict)
    if not norm["category"]:
        norm["category"] = "general"
    return norm


def suggest_portions(meal: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    user_prompt = json.dumps(
        {
            "meal": meal,
            "profile": profile or {},
            "instructions": {
                "shape": {"portions": ["str"], "swaps": ["str"], "caution": "str", "rationale": "str"}
            },
        },
        ensure_ascii=False,
    )
    resp = call_gemini(user_prompt=user_prompt, system_prompt=SYSTEM_PORTIONS, expect_json=True)
    data = resp if isinstance(resp, dict) else {"raw_text": str(resp)}
    portions = data.get("portions") or []
    swaps = data.get("swaps") or []
    caution = data.get("caution") or ""
    rationale = data.get("rationale") or ""
    # Fallbacks
    if not isinstance(portions, list) or not portions:
        portions = ["Add a serving of vegetables", "Include a protein source"]
    if not isinstance(swaps, list):
        swaps = []
    caution = str(caution or "Listen to your body and preferences.")
    rationale = str(rationale or "Simple, supportive portion guidance.")
    return {"portions": portions, "swaps": swaps, "caution": caution, "rationale": rationale}


def daily_summary_and_goals(context: Dict[str, Any]) -> Dict[str, Any]:
    user_prompt = json.dumps(
        {
            "context": context,
            "instructions": {"shape": {"summary": ["str"], "micro_goals": ["str"]}},
        },
        ensure_ascii=False,
    )
    resp = call_gemini(user_prompt=user_prompt, system_prompt=SYSTEM_SUMMARY, expect_json=True)
    data = resp if isinstance(resp, dict) else {"raw_text": str(resp)}
    summary = data.get("summary") or []
    micro_goals = data.get("micro_goals") or []
    if not isinstance(summary, list) or not summary:
        summary = ["A few healthy moments stood out today."]
    if not isinstance(micro_goals, list) or not micro_goals:
        micro_goals = ["Drink water with your next break", "Take a short walk"]
    return {"summary": summary, "micro_goals": micro_goals}


def generate_suggestion(prompt: str) -> str:
    """Placeholder LLM call. Returns a canned response for now."""
    return "Stay hydrated and take a short walk today. 🌿"


