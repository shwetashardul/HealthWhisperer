from datetime import datetime, timedelta, date
import json
from typing import Any, Dict, List, Optional

import streamlit as st

from data.db import (
    get_session,
    get_user_by_email,
    create_user,
    get_profile,
    get_user_preferences,
    list_logs,
    add_log,
    add_nudge,
    update_nudge,
    upsert_rule_state,
)
from auth.guards import require_login
user = require_login()
from llm.gemini_client import (
    generate_motivational_headline,
    suggest_nudge,
    suggest_portions,
)
from features.nudges import record_nudge
from features.rules_engine import evaluate_rules, evaluate_due_nudges
from streamlit.runtime.scriptrunner import add_script_run_ctx
from data.db import verify_schema


st.set_page_config(page_title="Home • Health Whisperer", page_icon="🏠", layout="wide")

# Guard: ensure DB is initialized
ver = verify_schema()
if not ver.get("ok"):
    st.warning("Database not initialized. Return to landing to initialize.")
    st.stop()


HEADER_CSS = """
<style>
:root { --hw-primary:#3c9a6b; --hw-bg:#f7faf7; --hw-text:#101311; }
.sun-header { background: linear-gradient(135deg, rgba(255,245,230,.9) 0%, rgba(214,245,227,.9) 50%, rgba(198,239,206,.9) 100%); border:1px solid rgba(60,154,107,.15); border-radius:14px; padding:20px 18px; margin: 6px 0 14px; box-shadow:0 2px 10px rgba(60,154,107,.06), inset 0 0 60px rgba(255,212,94,.15); }
.chip { display:inline-block; padding:4px 10px; margin-right:6px; border-radius:999px; background:#eaf6ef; border:1px solid rgba(60,154,107,.2); color:#1b2a22; font-size:13px; }
.card { border:1px solid rgba(60,154,107,.15); border-radius:12px; padding:14px; background:#ffffffaa; }
</style>
"""
st.markdown(HEADER_CSS, unsafe_allow_html=True)


def compute_bmi(weight_kg: Optional[float], height_cm: Optional[float]) -> Dict[str, Any]:
    if not weight_kg or not height_cm or weight_kg <= 0 or height_cm <= 0:
        return {"bmi": None, "category": "unknown"}
    h_m = height_cm / 100.0
    bmi = round(weight_kg / (h_m * h_m), 1)
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


def get_demo_user() -> int:
    with get_session() as s:
        demo_email = st.session_state.get("demo_email") or "demo@example.com"
        st.session_state["demo_email"] = demo_email
        user = get_user_by_email(s, demo_email)
        if not user:
            user = create_user(s, email=demo_email, name="Demo", password_hash=None, preferences=None)
        return user.id


def get_profile_snapshot(user_id: int) -> Dict[str, Any]:
    with get_session() as s:
        prof = get_profile(s, user_id) or {}
        prefs = get_user_preferences(s, user_id)
    name = prof.get("name") or "Friend"
    first_name = str(name).split(" ")[0] if isinstance(name, str) and name else "Friend"
    bmi_info = compute_bmi(prof.get("weight_kg"), prof.get("height_cm"))
    water_ml = water_target_ml(prof.get("weight_kg"))
    goals = prof.get("goals") or []
    return {"first_name": first_name, "bmi": bmi_info, "water_ml": water_ml, "goals": goals, "profile": prof, "prefs": prefs}


def recent_positive_strings(user_id: int) -> List[str]:
    with get_session() as s:
        rows = list_logs(s, user_id, limit=5)
    positives: List[str] = []
    for r in rows:
        if r["type"] == "physical":
            mins = (r.get("payload") or {}).get("minutes") or (r.get("payload") or {}).get("walk_min")
            if mins:
                positives.append(f"Walked {mins} minutes")
        elif r["type"] == "nutrition":
            water = (r.get("payload") or {}).get("water_ml")
            if water:
                positives.append(f"Drank {water} ml water")
        elif r["type"] == "mental":
            mood = (r.get("payload") or {}).get("mood")
            if mood:
                positives.append(f"Mood {mood}/5")
    return positives[:3]


user_id = get_demo_user()
snap = get_profile_snapshot(user_id)

# Headline using Gemini with fallback; never include medical details
positives = recent_positive_strings(user_id)
goal_hint = (snap["goals"][0] if isinstance(snap["goals"], list) and snap["goals"] else None)
headline = generate_motivational_headline(positives, snap["first_name"], goal_hint)

st.markdown(
    f"""
    <div class=\"sun-header\"> 
      <div style=\"font-weight:800;font-size:20px;color:#101311\">{headline}</div>
      <div style=\"margin-top:6px\"> 
        <span class=\"chip\">{snap['first_name']}</span>
        <span class=\"chip\">BMI: {snap['bmi']['category']}</span>
        <span class=\"chip\">Water: {snap['water_ml']} ml/day</span>
        {('<span class=\\"chip\\">Goal: ' + snap['goals'][0] + '</span>') if isinstance(snap['goals'], list) and len(snap['goals'])>0 else ''}
        {('<span class=\\"chip\\">Goal: ' + snap['goals'][1] + '</span>') if isinstance(snap['goals'], list) and len(snap['goals'])>1 else ''}
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.sidebar.caption(f"Notifications: {"" if False else ''}")
st.sidebar.write("Permission:", "<script>document.write(window.hwPermissionStatus ? hwPermissionStatus() : 'n/a')</script>", unsafe_allow_html=True)
if st.sidebar.button("🔔 Send test notification"):
    st.markdown("<script>window.hwEnsurePermission && hwEnsurePermission().then(()=>{ window.hwNotify && hwNotify('Test','This is a test.'); });</script>", unsafe_allow_html=True)


def privacy_aware_profile(prof: Dict[str, Any]) -> Dict[str, Any]:
    if not prof:
        return {}
    if not prof.get("share_profile_with_ai", True):
        return {
            "dietary_prefs": prof.get("dietary_prefs") or [],
            "activity_level": prof.get("activity_level"),
            "goals": prof.get("goals") or [],
            "share_profile_with_ai": False,
        }
    return {
        "dietary_prefs": prof.get("dietary_prefs") or [],
        "activity_level": prof.get("activity_level"),
        "goals": prof.get("goals") or [],
        "favorite_activities": prof.get("favorite_activities") or [],
        "happy_triggers": prof.get("happy_triggers") or [],
        "social_circle": prof.get("social_circle") or [],
        "medical_conditions": prof.get("medical_conditions") or [],
        "disabilities": prof.get("disabilities") or [],
        "share_profile_with_ai": True,
    }


def normalize_category(cat: Optional[str]) -> str:
    c = (cat or "").strip().lower()
    if c in {"mental", "nutrition", "physical"}:
        return c
    return "mental"


def show_nudge(n: Dict[str, Any], category: str) -> None:
    st.markdown("---")
    st.markdown(f"**{n.get('title','Nudge')}**")
    if n.get("body"):
        st.write(n.get("body"))
    if n.get("rationale"):
        st.caption(n.get("rationale"))
    colX, colY, colZ = st.columns(3)
    with colX:
        if st.button("Do it", key=f"do_{category}"):
            with get_session() as s:
                saved = add_nudge(s, user_id, category, n.get("title") or "Nudge", n.get("body"), n.get("rationale"), accepted=True)
            record_nudge(n.get("title") or "")
            st.success("Great! Logged as done.")
    with colY:
        if st.button("Snooze 10m", key=f"snooze_{category}"):
            with get_session() as s:
                saved = add_nudge(s, user_id, category, n.get("title") or "Nudge", n.get("body"), n.get("rationale"), accepted=None)
                upsert_rule_state(s, user_id, f"nudge:{saved.id}", snoozed_until=datetime.utcnow() + timedelta(minutes=10))
            st.info("Snoozed for 10 minutes.")
    with colZ:
        if st.button("Dismiss", key=f"dismiss_{category}"):
            with get_session() as s:
                saved = add_nudge(s, user_id, category, n.get("title") or "Nudge", n.get("body"), n.get("rationale"), accepted=False)
            st.warning("Dismissed.")


colA, colB, colC = st.columns(3)

with colA:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("🧠 Mental")
    mood_options = [
        (1, "Angry 😠"),
        (2, "Sad 😞"),
        (3, "Disheartened 😔"),
        (4, "Neutral 😐"),
        (5, "Okay 🙂"),
        (6, "Happy 🙂‍↕️"),
        (7, "Very happy 😄"),
    ]
    labels = [label for _, label in mood_options]
    selection = st.radio("How do you feel?", labels, horizontal=True, index=3)
    mood_score = next(score for score, label in mood_options if label == selection)
    mood_label = selection
    feelings_choices = ["stressed","anxious","overwhelmed","tired","low-energy","calm","focused","grateful","excited","other"]
    feelings = st.multiselect("Feelings right now (optional)", feelings_choices)
    note = st.text_input("Note (optional)")
    breath = st.checkbox("Breathwork done")
    if st.button("Save mental log"):
        with get_session() as s:
            add_log(s, user_id, "mental", {"mood_score": mood_score, "mood_label": mood_label, "feelings": feelings, "note": note, "breath": bool(breath), "ts": datetime.utcnow().isoformat()})
        st.success("Saved mental log.")
    crisis_terms = {"suicide", "self-harm", "kill myself", "end it", "overdose"}
    if st.button("Get mental nudge"):
        if any(t in (note or "").lower() for t in crisis_terms):
            st.error("If you’re in crisis, you’re not alone. Help is available.")
            st.markdown("[Get help](https://988lifeline.org/)")
        else:
            context = {
                "type": "mental",
                "profile": privacy_aware_profile(snap["profile"]),
                "current": {"mood_score": mood_score, "mood_label": mood_label, "feelings": feelings, "note": note, "breath": breath},
            }
            n = suggest_nudge(context)
            n["category"] = normalize_category("mental")
            show_nudge(n, n["category"])
            # Immediate browser pop-up
            title = n.get("title") or "Health Whisperer"
            body = n.get("body") or "Take a small healthy action."
            st.markdown(f"<script>window.hwNotify && hwNotify({json.dumps(title)}, {json.dumps(body)});</script>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

with colB:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("🥗 Nutrition")
    meal_time = st.selectbox("Meal time", ["breakfast", "lunch", "dinner", "snack"], index=1)
    hunger = st.slider("Hunger (1 low – 5 high)", 1, 5, 3)
    water_ml = st.number_input("Water (ml)", min_value=0, step=50, value=0)
    cuisine_tags = st.multiselect("Cuisine tags", ["Indian","Continental","Mediterranean","East Asian","Mexican","American","Other"])
    # Curated quick picks
    quick_map = {
        "breakfast": [
            "oatmeal + nuts","veggie omelet","yogurt parfait","smoothie (banana/spinach/peanut)","avocado toast","poha","upma","idli-sambar","dosa","paratha (veg)","cheela/pancakes","muesli & milk"
        ],
        "lunch": [
            "dal-chawal","roti-sabzi","paneer tikka + salad","grilled chicken + veggies","rajma-rice","khichdi","grain bowl","stir-fry (tofu + veg)","stir-fry (paneer + veg)","stir-fry (chicken + veg)","pasta + veggie sauce","soup + sandwich","tacos/burrito bowl","sushi rolls","Buddha bowl","baked fish + greens"
        ],
        "dinner": [
            "dal-chawal","roti-sabzi","paneer tikka + salad","grilled chicken + veggies","rajma-rice","khichdi","grain bowl","stir-fry (tofu + veg)","stir-fry (paneer + veg)","stir-fry (chicken + veg)","pasta + veggie sauce","soup + sandwich","tacos/burrito bowl","sushi rolls","Buddha bowl","baked fish + greens"
        ],
        "snack": [
            "fruit + nuts","chana/chickpeas","sprouts salad","hummus + veg sticks","yogurt","buttermilk","lemon water","herbal tea","coffee (milk/black)","coconut water"
        ],
    }
    # Filter by allergies/prefs
    allergies = set((snap["profile"].get("allergies") or [])) if snap["profile"] else set()
    prefs = set((snap["profile"].get("dietary_prefs") or [])) if snap["profile"] else set()
    def conflicts(item: str) -> bool:
        s = item.lower()
        if "nuts" in s and any("nut" in a.lower() for a in allergies):
            return True
        if "yogurt" in s or "milk" in s or "paneer" in s:
            if any("dairy" in p.lower() for p in prefs) or any("dairy" in a.lower() for a in allergies):
                return True
        if "egg" in s and any("egg" in a.lower() for a in allergies):
            return True
        if "fish" in s and any("fish" in a.lower() for a in allergies):
            return True
        return False
    quick_candidates = [i for i in quick_map[meal_time] if not conflicts(i)]
    filtered = len(quick_candidates) != len(quick_map[meal_time])
    picks = st.multiselect("Quick picks", quick_candidates)
    if filtered:
        st.caption("Some items hidden due to preferences/allergies.")
    custom_item = st.text_input("Custom add (optional)")
    if st.button("Add to picks") and custom_item.strip():
        picks = list(dict.fromkeys(picks + [custom_item.strip()]))
    items = ", ".join(picks)

    allergens = set((snap["profile"].get("allergies") or [])) if snap["profile"] else set()
    if items and allergens:
        tokens = [t.strip().lower() for t in items.split(",")]
        trigs = [a for a in allergens if any(a.lower() in t for t in tokens)]
        if trigs:
            st.error(f"Allergy warning: {', '.join(trigs)}")

    if st.button("Save nutrition log"):
        with get_session() as s:
            add_log(s, user_id, "nutrition", {"meal_time": meal_time, "items": picks, "cuisines": cuisine_tags, "hunger": hunger, "water_ml": int(water_ml), "ts": datetime.utcnow().isoformat()})
        st.success("Saved nutrition log.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Get portion advice"):
            meal = {"meal_time": meal_time, "items": picks, "hunger": hunger, "cuisines": cuisine_tags}
            pa = suggest_portions(meal, privacy_aware_profile(snap["profile"]))
            st.write("Portions:")
            for p in pa.get("portions", []):
                st.write(f"• {p}")
            if pa.get("swaps"):
                st.write("Swaps:")
                for s in pa["swaps"]:
                    st.write(f"• {s}")
            if pa.get("caution"):
                st.caption(pa["caution"]) 
            if pa.get("rationale"):
                st.caption(pa["rationale"]) 
    with c2:
        if st.button("Get nutrition nudge"):
            context = {
                "type": "nutrition",
                "profile": privacy_aware_profile(snap["profile"]),
                "current": {"meal_time": meal_time, "items": items, "hunger": hunger, "water_ml": int(water_ml)},
            }
            n = suggest_nudge(context)
            n["category"] = normalize_category("nutrition")
            show_nudge(n, n["category"])
            title = n.get("title") or "Health Whisperer"
            body = n.get("body") or "Take a small healthy action."
            st.markdown(f"<script>window.hwNotify && hwNotify({json.dumps(title)}, {json.dumps(body)});</script>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

with colC:
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.subheader("🏃 Physical")
    activity = st.selectbox("Activity", ["walk", "stretch", "yoga", "cycle", "run"], index=0)
    minutes = st.number_input("Minutes", min_value=0, step=5, value=10)
    rpe = st.slider("Effort (RPE)", 1, 10, 5)
    if st.button("Log 2-min stretch now"):
        with get_session() as s:
            add_log(s, user_id, "physical", {"activity": "stretch", "minutes": 2, "rpe": 1, "ts": datetime.utcnow().isoformat()})
        st.success("Logged a quick stretch.")
    if st.button("Save physical log"):
        with get_session() as s:
            add_log(s, user_id, "physical", {"activity": activity, "minutes": int(minutes), "rpe": rpe, "ts": datetime.utcnow().isoformat()})
        st.success("Saved physical log.")
    if st.button("Get physical nudge"):
        context = {
            "type": "physical",
            "profile": privacy_aware_profile(snap["profile"]),
            "current": {"activity": activity, "minutes": int(minutes), "rpe": rpe},
        }
        n = suggest_nudge(context)
        n["category"] = normalize_category("physical")
        # If contraindications exist, lightly adjust body text locally as a final safety net
        contraindications = (snap["profile"].get("medical_conditions") or []) + (snap["profile"].get("disabilities") or [])
        if contraindications and "joint" in ",".join([str(x).lower() for x in contraindications]):
            if "stretch" not in (n.get("body") or "").lower():
                n["body"] = (n.get("body") or "").strip() + " Consider a seated stretch if joints feel sensitive."
        show_nudge(n, n["category"])
        title = n.get("title") or "Health Whisperer"
        body = n.get("body") or "Take a small healthy action."
        st.markdown(f"<script>window.hwNotify && hwNotify({json.dumps(title)}, {json.dumps(body)});</script>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# Sidebar controls for auto-nudges
st.sidebar.subheader("Auto-nudges")
enable_auto = st.sidebar.toggle("Enable auto-nudges", value=True)
show_debug = st.sidebar.toggle("Show debug", value=False)
# Pull defaults from preferences if available
pref_qs = (snap.get("prefs", {}).get("quiet_hours", {}) if snap.get("prefs") else {})
def_time = lambda s, d: datetime.strptime(str(pref_qs.get(s, d)), "%H:%M").time() if isinstance(pref_qs.get(s, d), str) else datetime.strptime(d, "%H:%M").time()
quiet_start = st.sidebar.time_input("Quiet start", value=def_time("start","22:00"))
quiet_end = st.sidebar.time_input("Quiet end", value=def_time("end","07:00"))
cool_hyd = st.sidebar.slider("Hydration cooldown (min)", 5, 60, 15)
cool_meal = st.sidebar.slider("Meals cooldown (min)", 30, 240, 120)
cool_phys = st.sidebar.slider("Physical cooldown (min)", 30, 240, 120)

if enable_auto:
    # periodic evaluation every ~75s (JS-based refresh to avoid API differences)
    st.markdown("<script>setTimeout(function(){ location.reload(); }, 60000);</script>", unsafe_allow_html=True)

settings = {
    "quiet_start": quiet_start,
    "quiet_end": quiet_end,
    "cooldown_hydration": cool_hyd,
    "cooldown_meals": cool_meal,
    "cooldown_physical": cool_phys,
}

if enable_auto:
    with get_session() as s:
        fired = evaluate_due_nudges(s, user_id=user_id, profile=snap["profile"], settings=settings)
        # create debug summary minimal
        dbg = {"fired": [f["rule_id"] for f in fired], "suppressed": []}
        for r in fired:
            # persist rules_state update
            upsert_rule_state(s, user_id, r["rule_id"], last_fired_at=datetime.utcnow(), fired_on_date=date.today())
        for r in fired:
            # try browser notification
            title = r.get("title") or "Health Whisperer"
            body = r.get("body") or "Take a small healthy action."
            st.markdown(f"<script>var s=(window.hwNotify? hwNotify({json.dumps(title)}, {json.dumps(body)}):'unsupported'); if(s!=='shown') window._hw_last='fallback';</script>", unsafe_allow_html=True)
            # Streamlit fallback toast/modal
            with st.expander(f"{title}"):
                st.write(body)
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("Do it", key=f"auto_do_{r['rule_id']}"):
                        with get_session() as s2:
                            add_nudge(s2, user_id, r.get("category"), title, body, "auto-nudge", True)
                        st.success("Nice!")
                with col2:
                    if st.button("Snooze 10m", key=f"auto_snooze_{r['rule_id']}"):
                        with get_session() as s2:
                            upsert_rule_state(s2, user_id, r["rule_id"], snoozed_until=datetime.utcnow() + timedelta(minutes=10))
                        st.info("Snoozed.")
                with col3:
                    if st.button("Dismiss", key=f"auto_dismiss_{r['rule_id']}"):
                        with get_session() as s2:
                            add_nudge(s2, user_id, r.get("category"), title, body, "auto-nudge", False)
                        st.warning("Dismissed.")

    if show_debug:
        st.sidebar.write("Last evaluation:", datetime.utcnow().isoformat())
        st.sidebar.write("Fired:", dbg.get("fired"))
        st.sidebar.write("Suppressed:", dbg.get("suppressed"))
        debug_state = st.session_state.get("debug", {})
        if debug_state.get("last_gemini_text"):
            st.sidebar.write("Last Gemini:")
            st.sidebar.code(str(debug_state.get("last_gemini_text"))[:1000])



