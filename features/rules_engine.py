from datetime import datetime, time, timedelta, date
from typing import Dict, List, Optional, Tuple

from data.db import list_logs, upsert_rule_state, get_rule_state


def is_within_quiet_hours(now: Optional[datetime] = None, start: time = time(22, 0), end: time = time(7, 0)) -> bool:
    now = now or datetime.now()
    if start <= end:
        return start <= now.time() <= end
    return now.time() >= start or now.time() <= end


def next_nudge_after(cooldown_minutes: int = 60) -> datetime:
    return datetime.now() + timedelta(minutes=cooldown_minutes)


def _today_range(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    now = now or datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return start, end

def _minutes_diff(a: datetime, b: datetime) -> int:
    return int((a - b).total_seconds() // 60)


def evaluate_rules(
    session,
    *,
    user_id: int,
    profile: Dict,
    settings: Dict,
    now: Optional[datetime] = None,
) -> Tuple[List[Dict], Dict]:
    """Return (fired_rules, debug). Fired rule entries contain: rule_id, title, body, category."""
    now = now or datetime.utcnow()
    debug: Dict[str, List[str]] = {"suppressed": [], "fired": [], "info": []}

    # Quiet hours
    q_start: time = settings.get("quiet_start", time(22, 0))
    q_end: time = settings.get("quiet_end", time(7, 0))
    if is_within_quiet_hours(now, q_start, q_end):
        debug["suppressed"].append("quiet_hours")
        return [], debug

    start_today, _ = _today_range(now)

    def _cooldown_ok(rule_id: str, cd_minutes: int) -> bool:
        rs = get_rule_state(session, user_id, rule_id)
        if rs and rs.snoozed_until and rs.snoozed_until > now:
            debug["suppressed"].append(f"{rule_id}: snoozed")
            return False
        if rs and rs.last_fired_at and _minutes_diff(now, rs.last_fired_at) < cd_minutes:
            debug["suppressed"].append(f"{rule_id}: cooldown")
            return False
        return True

    fired: List[Dict] = []

    # Gather today's logs
    todays_nutrition = list_logs(session, user_id, log_type="nutrition", since=start_today)
    todays_physical = list_logs(session, user_id, log_type="physical", since=start_today)

    # hydration_10m
    hyd_cd = int(settings.get("cooldown_hydration", 15))
    last_water_ts: Optional[datetime] = None
    for r in todays_nutrition:
        payload = r.get("payload") or {}
        if (payload.get("water_ml") or 0) > 0:
            if not last_water_ts or r["ts"] > last_water_ts:
                last_water_ts = r["ts"]
    mins_since = _minutes_diff(now, last_water_ts) if last_water_ts else 10**6
    if mins_since >= 1 and _cooldown_ok("hydration_10m", hyd_cd):
        target_ml = int((profile or {}).get("weight_kg") or 0) * 30
        if target_ml <= 0:
            target_ml = 2000
        target_ml = min(max(target_ml, 1200), 3500)
        fired.append({
            "rule_id": "hydration_10m",
            "title": "Sip water",
            "body": f"It’s been a while. Target around {target_ml} ml/day.",
            "category": "nutrition",
        })
        debug["fired"].append("hydration_10m")

    # meals: breakfast_9am, lunch_13pm, dinner_19pm – fire once per day
    def _meal_missing(meal: str) -> bool:
        for r in todays_nutrition:
            payload = r.get("payload") or {}
            if (payload.get("meal_time") or "").lower() == meal:
                return False
        return True

    meal_rules = [
        ("breakfast_9am", "breakfast", time(9, 0)),
        ("lunch_13pm", "lunch", time(13, 0)),
        ("dinner_19pm", "dinner", time(19, 0)),
    ]
    meal_cd = int(settings.get("cooldown_meals", 120))
    for rule_id, meal, rule_time in meal_rules:
        rs = get_rule_state(session, user_id, rule_id)
        if now.time() >= rule_time:
            if _meal_missing(meal):
                # ensure once per day
                if not (rs and rs.fired_on_date == date.today()) and _cooldown_ok(rule_id, meal_cd):
                    fired.append({
                        "rule_id": rule_id,
                        "title": f"{meal.title()} check-in",
                        "body": f"Have you had {meal} today? A balanced plate helps energy.",
                        "category": "nutrition",
                    })
                    debug["fired"].append(rule_id)
            else:
                debug["suppressed"].append(f"{rule_id}: already_logged")

    # walk_eod_21pm – after 21:00 if walking minutes today below target
    phys_cd = int(settings.get("cooldown_physical", 120))
    if now.time() >= time(21, 0):
        total_min = 0
        for r in todays_physical:
            payload = r.get("payload") or {}
            total_min += int(payload.get("minutes") or payload.get("walk_min") or 0)
        act = (profile or {}).get("activity_level") or ""
        act_lower = str(act).lower()
        if act_lower in {"low", "lightly_active"}:
            target = 60
        elif act_lower in {"moderate", "moderately_active"}:
            target = 75
        else:
            target = 90
        rs = get_rule_state(session, user_id, "walk_eod_21pm")
        if total_min < target:
            if not (rs and rs.fired_on_date == date.today()) and _cooldown_ok("walk_eod_21pm", phys_cd):
                fired.append({
                    "rule_id": "walk_eod_21pm",
                    "title": "Evening movement",
                    "body": f"You’ve logged {total_min} min today. Aim for about {target}.",
                    "category": "physical",
                })
                debug["fired"].append("walk_eod_21pm")
        else:
            debug["suppressed"].append("walk_eod_21pm: target_met")

    return fired, debug


def evaluate_due_nudges(session, *, user_id: int, profile: Dict, settings: Dict, now: Optional[datetime] = None) -> List[Dict]:
    fired, _ = evaluate_rules(session, user_id=user_id, profile=profile, settings=settings, now=now)
    # Add sedentary_60m rule here (separate from EOD walk target)
    now = now or datetime.utcnow()
    start_today, _ = _today_range(now)
    phys = list_logs(session, user_id, log_type="physical", since=start_today)
    last_phys = None
    for r in phys:
        if not last_phys or r["ts"] > last_phys:
            last_phys = r["ts"]
    mins = _minutes_diff(now, last_phys) if last_phys else 10**6
    cd = int(settings.get("cooldown_sedentary", 30))
    rs = get_rule_state(session, user_id, "sedentary_60m")
    if not (rs and rs.fired_on_date == date.today()) and mins >= 60:
        if not (rs and rs.snoozed_until and rs.snoozed_until > now) and not (rs and rs.last_fired_at and _minutes_diff(now, rs.last_fired_at) < cd):
            body = "You’ve been sitting ~1h. Stand up for 2–3 minutes or walk 200 steps."
            contraindications = (profile or {}).get("medical_conditions") or []
            disabilities = (profile or {}).get("disabilities") or []
            s = ",".join([str(x).lower() for x in contraindications + disabilities])
            if "joint" in s:
                body = "Gentle stretch break: try a seated stretch or neck/shoulder roll."
            fired.append({
                "rule_id": "sedentary_60m",
                "category": "physical",
                "title": "🚶 Time to move",
                "body": body,
                "rationale": "No movement in ~60 minutes.",
            })
    return fired



