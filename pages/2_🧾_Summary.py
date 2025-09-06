from auth.guards import require_login
user = require_login()
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import plotly.express as px
import streamlit as st

from data.db import get_session, get_user_by_email, create_user, get_profile, list_logs, list_nudges, verify_schema, db_info
from llm.gemini_client import daily_summary_and_goals


st.set_page_config(page_title="Summary • Health Whisperer", page_icon="🧾", layout="wide")

st.title("🧾 Summary")

# Guard: ensure DB is initialized
ver = verify_schema()
if not ver.get("ok"):
    st.warning("Database not initialized. Return to landing to initialize.")
    st.stop()


def today_bounds(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day)


def privacy_aware_context(profile: Dict[str, Any]) -> Dict[str, Any]:
    if not profile:
        return {}
    if not profile.get("share_profile_with_ai", True):
        return {
            "dietary_prefs": profile.get("dietary_prefs") or [],
            "activity_level": profile.get("activity_level"),
            "goals": profile.get("goals") or [],
            "share_profile_with_ai": False,
        }
    return profile


now = datetime.utcnow()
start = today_bounds(now)

with get_session() as s:
    demo_email = st.session_state.get("demo_email") or "demo@example.com"
    st.session_state["demo_email"] = demo_email
    user = get_user_by_email(s, demo_email)
    if not user:
        user = create_user(s, email=demo_email, name="Demo", password_hash=None, preferences=None)
    user_id = user.id
    profile = get_profile(s, user_id) or {}
    logs = list_logs(s, user_id, since=start)
    nudges = list(filter(lambda n: isinstance(n, dict), list_nudges(s, user_id, limit=200)))


# Compute today's metrics
hydration_total = sum(int((l.get("payload") or {}).get("water_ml") or 0) for l in logs if l["type"] == "nutrition")
walking_minutes = sum(int((l.get("payload") or {}).get("minutes") or (l.get("payload") or {}).get("walk_min") or 0) for l in logs if l["type"] == "physical")
mental_positives = 0
for l in logs:
    if l["type"] != "mental":
        continue
    payload = l.get("payload") or {}
    score = int(payload.get("mood_score") or 0)
    if score >= 6 or payload.get("breath") is True:
        mental_positives += 1
nudges_today = [n for n in nudges if isinstance(n.get("ts"), datetime) and n["ts"] >= start]
nudges_accepted = [n for n in nudges_today if n.get("accepted") is True]
accept_rate = round((len(nudges_accepted) / len(nudges_today) * 100.0), 1) if nudges_today else 0.0
counts_by_type = {
    "mental": sum(1 for l in logs if l["type"] == "mental"),
    "nutrition": sum(1 for l in logs if l["type"] == "nutrition"),
    "physical": sum(1 for l in logs if l["type"] == "physical"),
}


# Compact context for LLM
ctx = {
    "today": {
        "hydration_total_ml": hydration_total,
        "walking_minutes": walking_minutes,
        "mental_positives": mental_positives,
        "logs_counts": counts_by_type,
        "nudges": {"accepted": len(nudges_accepted), "total": len(nudges_today), "accept_rate": accept_rate},
    },
    "profile_hints": {
        "goals": profile.get("goals") or [],
        "activity_level": profile.get("activity_level"),
    },
}

try:
    llm_ctx = {"context": ctx, "profile": privacy_aware_context(profile)}
    llm = daily_summary_and_goals(llm_ctx)
    summary_points = llm.get("summary") or []
    micro_goals = llm.get("micro_goals") or []
except Exception:
    summary_points = [
        f"Hydration: {hydration_total} ml",
        f"Walking: {walking_minutes} min",
        f"Mental positives: {mental_positives}",
    ]
    micro_goals = ["Sip water with each break", "Short walk after lunch"]


# Render bullets
st.subheader("Today at a glance")
for point in summary_points[:3]:
    st.write(f"• {point}")

st.subheader("Micro-goals for tomorrow")
for g in micro_goals[:3]:
    st.write(f"• {g}")


# Mini-charts
col1, col2, col3 = st.columns(3)
with col1:
    df_h = pd.DataFrame({"metric": ["Hydration"], "value": [hydration_total]})
    st.plotly_chart(px.bar(df_h, x="metric", y="value", title="Hydration (ml)"), use_container_width=True)
with col2:
    df_p = pd.DataFrame({"metric": ["Walking"], "value": [walking_minutes]})
    st.plotly_chart(px.bar(df_p, x="metric", y="value", title="Walking (min)"), use_container_width=True)
with col3:
    df_m = pd.DataFrame({"type": list(counts_by_type.keys()), "count": list(counts_by_type.values())})
    st.plotly_chart(px.pie(df_m, names="type", values="count", title="Logs by type"), use_container_width=True)


# Exports
def to_csv(rows: List[Dict[str, Any]]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def to_json(rows: List[Dict[str, Any]]) -> str:
    import json as _json

    return _json.dumps(rows, default=str)


colA, colB = st.columns(2)
with colA:
    st.download_button("Export today's logs (CSV)", data=to_csv(logs), file_name="logs_today.csv", mime="text/csv")
    st.download_button("Export today's logs (JSON)", data=to_json(logs), file_name="logs_today.json", mime="application/json")
with colB:
    st.download_button("Export today's nudges (CSV)", data=to_csv(nudges_today), file_name="nudges_today.csv", mime="text/csv")
    st.download_button("Export today's nudges (JSON)", data=to_json(nudges_today), file_name="nudges_today.json", mime="application/json")


