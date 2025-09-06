from datetime import datetime
from typing import Any, Dict, List, Optional

from .db import (
    get_session,
    get_user_by_id,
    get_profile,
    list_logs,
    list_nudges,
    list_rule_states,
)


def _today_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def hydration_total_today(user_id: int) -> int:
    start = _today_start()
    with get_session() as s:
        rows = list_logs(s, user_id, log_type="nutrition", since=start)
    return sum(int((r.get("payload") or {}).get("water_ml") or 0) for r in rows)


def walk_minutes_today(user_id: int) -> int:
    start = _today_start()
    with get_session() as s:
        rows = list_logs(s, user_id, log_type="physical", since=start)
    total = 0
    for r in rows:
        payload = r.get("payload") or {}
        total += int(payload.get("minutes") or payload.get("walk_min") or 0)
    return total


def has_meal_today(user_id: int, meal: str) -> bool:
    start = _today_start()
    meal_l = (meal or "").lower()
    with get_session() as s:
        rows = list_logs(s, user_id, log_type="nutrition", since=start)
    for r in rows:
        payload = r.get("payload") or {}
        if (payload.get("meal_time") or "").lower() == meal_l:
            return True
    return False


def get_user_bundle(user_id: int) -> Dict[str, Any]:
    """Return a JSON-ready bundle: user, profile, logs, nudges, rules_state."""
    with get_session() as s:
        user = get_user_by_id(s, user_id)
        profile = get_profile(s, user_id) or {}
        logs = list_logs(s, user_id, log_type=None)
        nudges = list_nudges(s, user_id)
        rules = list_rule_states(s, user_id)

    user_dict = {
        "id": user.id if user else None,
        "email": user.email if user else None,
        "name": user.name if user else None,
        "created_at": user.created_at if user else None,
        "updated_at": user.updated_at if user else None,
    }

    def _rs_to_dict(rs) -> Dict[str, Any]:
        return {
            "id": rs.id,
            "user_id": rs.user_id,
            "rule_id": rs.rule_id,
            "last_fired_at": rs.last_fired_at,
            "snoozed_until": rs.snoozed_until,
            "fired_on_date": rs.fired_on_date,
        }

    return {
        "user": user_dict,
        "profile": profile,
        "logs": logs,
        "nudges": nudges,
        "rules_state": [_rs_to_dict(r) for r in rules],
    }


