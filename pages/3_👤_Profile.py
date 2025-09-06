import math
from datetime import date
from typing import Any, Dict, List, Optional

import streamlit as st

from auth.guards import require_login
user = require_login()
from data.db import get_session, get_profile, upsert_profile, get_user_by_email, create_user, get_user_preferences, update_user_preferences, verify_schema


st.set_page_config(page_title="Profile • Health Whisperer", page_icon="👤", layout="wide")

st.title("👤 Profile")

# Guard: ensure DB is initialized
ver = verify_schema()
if not ver.get("ok"):
    st.warning("Database not initialized. Return to landing to initialize.")
    st.stop()


def cm_to_ft_in(cm: Optional[float]) -> Dict[str, int]:
    if not cm or cm <= 0:
        return {"ft": 0, "in": 0}
    total_in = cm / 2.54
    ft = int(total_in // 12)
    inches = int(round(total_in - ft * 12))
    if inches == 12:
        ft += 1
        inches = 0
    return {"ft": ft, "in": inches}


def ft_in_to_cm(ft: int, inches: int) -> float:
    ft = max(0, int(ft))
    inches = max(0, int(inches))
    return round((ft * 12 + inches) * 2.54, 1)


def kg_to_lb(kg: Optional[float]) -> float:
    if not kg or kg <= 0:
        return 0.0
    return round(kg * 2.2046226218, 1)


def lb_to_kg(lb: Optional[float]) -> float:
    if not lb or lb <= 0:
        return 0.0
    return round(lb / 2.2046226218, 1)


def compute_bmi(weight_kg: Optional[float], height_cm: Optional[float]) -> Dict[str, Any]:
    if not weight_kg or not height_cm or weight_kg <= 0 or height_cm <= 0:
        return {"bmi": None, "category": "unknown"}
    h_m = height_cm / 100.0
    bmi = weight_kg / (h_m * h_m)
    bmi = round(bmi, 1)
    if bmi < 18.5:
        cat = "underweight"
    elif bmi < 25:
        cat = "normal"
    elif bmi < 30:
        cat = "overweight"
    else:
        cat = "obese"
    return {"bmi": bmi, "category": cat}


def water_target_ml(weight_kg: Optional[float], cap: int = 3500) -> int:
    if not weight_kg or weight_kg <= 0:
        return 1500
    ml = int(weight_kg * 30)
    return min(max(ml, 1200), cap)


def kcal_band(activity: str) -> str:
    bands = {
        "low": "~1600–2000 kcal",
        "moderate": "~2000–2400 kcal",
        "high": "~2400–3000 kcal",
    }
    return bands.get((activity or "").lower(), "varies by individual")


def validate_ranges(dob: Optional[date], height_cm: Optional[float], weight_kg: Optional[float]) -> List[str]:
    warnings: List[str] = []
    # DOB validation
    if dob:
        today = date.today()
        if dob >= today:
            warnings.append("DOB must be in the past.")
        else:
            age = (today - dob).days // 365
            if age < 10 or age > 110:
                warnings.append("Age seems out of expected range (10–110).")
    # Height
    if height_cm:
        if height_cm < 120 or height_cm > 230:
            warnings.append("Height seems out of expected range (120–230 cm).")
    # Weight
    if weight_kg:
        if weight_kg < 30 or weight_kg > 250:
            warnings.append("Weight seems out of expected range (30–250 kg).")
    return warnings


with get_session() as s:
    # Simple demo: use a single demo user stored in session
    demo_email = st.session_state.get("demo_email") or "demo@example.com"
    st.session_state["demo_email"] = demo_email
    user = get_user_by_email(s, demo_email)
    if not user:
        user = create_user(s, email=demo_email, name="Demo", password_hash=None, preferences=None)
    user_id = user.id

    existing = get_profile(s, user_id) or {}
    prefs = get_user_preferences(s, user_id)

with st.form("profile_form"):
    st.subheader("Identity")
    col1, col2, col3 = st.columns(3)
    with col1:
        name = st.text_input("Name", value=existing.get("name", ""))
    with col2:
        dob = st.date_input("Date of birth", value=existing.get("dob") or date(1990, 1, 1), max_value=date.today())
    with col3:
        sex = st.selectbox("Sex", options=["", "F", "M", "Other"], index=["", "F", "M", "Other"].index(existing.get("sex", "")))

    st.subheader("Body metrics")
    h_cm = existing.get("height_cm") or 170.0
    w_kg = existing.get("weight_kg") or 70.0
    h_ftin = cm_to_ft_in(h_cm)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        height_cm = st.number_input("Height (cm)", min_value=0.0, max_value=300.0, step=0.5, value=float(h_cm))
    with c2:
        ft = st.number_input("Height ft", min_value=0, max_value=8, value=int(h_ftin["ft"]))
    with c3:
        inch = st.number_input("Height in", min_value=0, max_value=11, value=int(h_ftin["in"]))
    with c4:
        weight_kg = st.number_input("Weight (kg)", min_value=0.0, max_value=400.0, step=0.5, value=float(w_kg))

    # Live conversions
    conv_left, conv_right = st.columns(2)
    with conv_left:
        if st.checkbox("Update height cm from ft/in", value=True):
            height_cm = ft_in_to_cm(ft, inch)
        st.caption(f"≈ {ft} ft {inch} in")
    with conv_right:
        weight_lb = kg_to_lb(weight_kg)
        st.caption(f"≈ {weight_lb} lb")

    st.subheader("Health")
    disabilities = st.text_area("Disabilities (comma-separated)", value=", ".join((existing.get("disabilities") or []) if isinstance(existing.get("disabilities"), list) else (existing.get("disabilities") or []) if isinstance(existing.get("disabilities"), list) else []))
    medical_conditions = st.text_area("Medical conditions (comma-separated)", value=", ".join((existing.get("medical_conditions") or []) if isinstance(existing.get("medical_conditions"), list) else []))
    allergies = st.text_area("Allergies (comma-separated)", value=", ".join((existing.get("allergies") or []) if isinstance(existing.get("allergies"), list) else []))

    st.subheader("Lifestyle")
    dietary_prefs = st.text_area("Dietary preferences (comma-separated)", value=", ".join((existing.get("dietary_prefs") or []) if isinstance(existing.get("dietary_prefs"), list) else []))
    activity_level = st.selectbox("Activity level", ["", "low", "moderate", "high"], index=["", "low", "moderate", "high"].index(existing.get("activity_level", "")))
    goals = st.text_area("Goals (comma-separated)", value=", ".join((existing.get("goals") or []) if isinstance(existing.get("goals"), list) else []))

    st.subheader("Personal joy")
    favorite_activities = st.text_area("Favorite activities (comma-separated)", value=", ".join((existing.get("favorite_activities") or []) if isinstance(existing.get("favorite_activities"), list) else []))
    happy_triggers = st.text_area("Happy triggers (comma-separated)", value=", ".join((existing.get("happy_triggers") or []) if isinstance(existing.get("happy_triggers"), list) else []))
    social_circle = st.text_area("Social circle (names, comma-separated)", value=", ".join((existing.get("social_circle") or []) if isinstance(existing.get("social_circle"), list) else []))

    st.subheader("Notes")
    doctor_notes = st.text_area("Doctor notes (not shared with AI)", value=existing.get("doctor_notes", ""))

    share_profile_with_ai = st.checkbox("Share profile context with AI (Gemini)", value=bool(existing.get("share_profile_with_ai", True)))

    st.subheader("Preferences")
    colp1, colp2, colp3, colp4 = st.columns(4)
    with colp1:
        primary_focus = st.selectbox("Primary focus", ["hydration", "stress", "activity", "nutrition"], index=["hydration","stress","activity","nutrition"].index(str(prefs.get("primary_focus","hydration"))))
    with colp2:
        tz = st.text_input("Time zone", value=str(prefs.get("timezone","America/Chicago")))
    with colp3:
        q_start = st.text_input("Quiet start (HH:MM)", value=str(prefs.get("quiet_hours",{}).get("start","22:00")))
    with colp4:
        q_end = st.text_input("Quiet end (HH:MM)", value=str(prefs.get("quiet_hours",{}).get("end","07:00")))

    submitted = st.form_submit_button("Save profile")

if submitted:
    warnings = validate_ranges(dob, height_cm, weight_kg)
    for w in warnings:
        st.warning(w)

    # Prepare JSON-like lists from comma-separated inputs
    def parse_list(text: str) -> List[str]:
        return [t.strip() for t in (text or "").split(",") if t.strip()]

    with get_session() as s:
        upsert_profile(
            s,
            user_id=user_id,
            dob=dob,
            sex=sex or None,
            height_cm=float(height_cm) if height_cm else None,
            weight_kg=float(weight_kg) if weight_kg else None,
            activity_level=activity_level or None,
            dietary_prefs=parse_list(dietary_prefs),
            allergies=parse_list(allergies),
            medical_conditions=parse_list(medical_conditions),
            disabilities=parse_list(disabilities),
            goals=parse_list(goals),
            favorite_activities=parse_list(favorite_activities),
            happy_triggers=parse_list(happy_triggers),
            social_circle=parse_list(social_circle),
            doctor_notes=doctor_notes or None,
            share_profile_with_ai=bool(share_profile_with_ai),
        )
    st.success("Profile saved.")
    with get_session() as s:
        update_user_preferences(s, user_id, {
            "share_profile_with_ai": bool(share_profile_with_ai),
            "primary_focus": primary_focus,
            "timezone": tz,
            "quiet_hours": {"start": q_start, "end": q_end},
        })

# Load latest state for summary
with get_session() as s:
    prof = get_profile(s, user_id)

bmi_info = compute_bmi(prof.get("weight_kg"), prof.get("height_cm")) if prof else {"bmi": None, "category": "unknown"}
water_ml = water_target_ml(prof.get("weight_kg")) if prof else 1500

st.subheader("Summary")
colA, colB, colC = st.columns(3)
with colA:
    st.metric("Name", (name or prof.get("name") or "Friend") if prof else (name or "Friend"))
with colB:
    st.metric("BMI", f"{bmi_info['bmi']} ({bmi_info['category']})" if bmi_info.get("bmi") else "–")
with colC:
    st.metric("Water target", f"{water_ml} ml/day")

if prof:
    st.caption(f"Activity: {prof.get('activity_level') or 'n/a'} • Suggested kcal band: {kcal_band(prof.get('activity_level') or '')}")
    goals_list = prof.get("goals") or []
    if isinstance(goals_list, list) and goals_list:
        st.write("Top goals:")
        st.write("• " + "\n• ".join(goals_list[:3]))


