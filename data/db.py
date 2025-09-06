import os
import json
from contextlib import contextmanager
from datetime import datetime, date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy import inspect


# Database URL preference: env var or default to project-local SQLite file
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///health_whisperer.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# -----------------------------
# Models
# -----------------------------


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)
    preferences = Column(Text, nullable=True)  # JSON as TEXT
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    profile = relationship("Profile", back_populates="user", uselist=False, cascade="all, delete")


class Profile(Base):
    __tablename__ = "profiles"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    dob = Column(Date, nullable=True)
    sex = Column(String(32), nullable=True)
    height_cm = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    activity_level = Column(String(64), nullable=True)
    dietary_prefs = Column(Text, nullable=True)  # JSON
    allergies = Column(Text, nullable=True)  # JSON
    medical_conditions = Column(Text, nullable=True)  # JSON
    disabilities = Column(Text, nullable=True)  # JSON
    goals = Column(Text, nullable=True)  # JSON
    favorite_activities = Column(Text, nullable=True)  # JSON
    happy_triggers = Column(Text, nullable=True)  # JSON
    social_circle = Column(Text, nullable=True)  # JSON of names
    doctor_notes = Column(Text, nullable=True)
    share_profile_with_ai = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="profile")


class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(32), nullable=False)
    payload = Column(Text, nullable=True)  # JSON
    ts = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("type in ('mental','nutrition','physical')", name="ck_logs_type"),
        Index("ix_logs_user_type_ts", "user_id", "type", "ts"),
    )


class Nudge(Base):
    __tablename__ = "nudges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(64), nullable=True, index=True)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=True)
    rationale = Column(Text, nullable=True)
    accepted = Column(Boolean, nullable=True)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_nudges_user_category_ts", "user_id", "category", "ts"),
    )


class RuleState(Base):
    __tablename__ = "rules_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = Column(String(128), nullable=False)
    last_fired_at = Column(DateTime, nullable=True)
    snoozed_until = Column(DateTime, nullable=True)
    fired_on_date = Column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "rule_id", name="uq_rules_state_user_rule"),
        Index("ix_rules_state_user_rule", "user_id", "rule_id"),
    )


# -----------------------------
# Utilities
# -----------------------------


def _dump_json(data: Any) -> Optional[str]:
    if data is None:
        return None
    return json.dumps(data, separators=(",", ":"))


def _load_json(text: Optional[str]) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


# -----------------------------
# Session helpers
# -----------------------------


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def db_info() -> Dict[str, Any]:
    is_sqlite = DATABASE_URL.startswith("sqlite")
    sqlite_path = None
    if is_sqlite:
        # sqlite:///health_whisperer.db → health_whisperer.db
        path = DATABASE_URL.replace("sqlite:///", "")
        sqlite_path = os.path.abspath(path)
    return {
        "url": DATABASE_URL,
        "dialect": engine.dialect.name,
        "is_sqlite": is_sqlite,
        "sqlite_path": sqlite_path,
    }


def verify_schema() -> Dict[str, Any]:
    insp = inspect(engine)
    tables = insp.get_table_names()
    core = {"users", "profiles", "logs", "nudges", "rules_state"}
    created_now = False
    ok = core.issubset(set(tables))
    if not ok:
        Base.metadata.create_all(bind=engine)
        created_now = True
        tables = inspect(engine).get_table_names()
        ok = core.issubset(set(tables))
    return {"ok": ok, "tables": tables, "created_now": created_now}


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """Legacy generator compatibility for Streamlit patterns."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------------
# CRUD: Users
# -----------------------------


def create_user(session, email: str, name: Optional[str] = None, password_hash: Optional[str] = None, preferences: Optional[Dict[str, Any]] = None) -> User:
    user = User(
        email=email,
        name=name,
        password_hash=password_hash,
        preferences=_dump_json(preferences),
    )
    session.add(user)
    session.flush()
    return user


def get_user_by_id(session, user_id: int) -> Optional[User]:
    return session.get(User, user_id)


def get_user_by_email(session, email: str) -> Optional[User]:
    return session.query(User).filter(User.email == email).one_or_none()


def update_user(session, user_id: int, **fields) -> Optional[User]:
    user = get_user_by_id(session, user_id)
    if not user:
        return None
    if "preferences" in fields:
        fields["preferences"] = _dump_json(fields["preferences"])
    for key, value in fields.items():
        if hasattr(user, key):
            setattr(user, key, value)
    session.flush()
    return user


def delete_user(session, user_id: int) -> bool:
    user = get_user_by_id(session, user_id)
    if not user:
        return False
    session.delete(user)
    session.flush()
    return True


def get_user_preferences(session, user_id: int) -> Dict[str, Any]:
    user = session.get(User, user_id)
    defaults: Dict[str, Any] = {
        "share_profile_with_ai": True,
        "quiet_hours": {"start": "22:00", "end": "07:00"},
        "primary_focus": "hydration",
        "timezone": "America/Chicago",
        "crisis_help_text": "Get help",
        "crisis_help_url": "https://988lifeline.org/",
    }
    if not user or not user.preferences:
        return defaults
    try:
        data = json.loads(user.preferences)
        if not isinstance(data, dict):
            return defaults
        return {**defaults, **data}
    except Exception:
        return defaults


def update_user_preferences(session, user_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    user = session.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    current = get_user_preferences(session, user_id)
    merged = {**current, **(updates or {})}
    user.preferences = json.dumps(merged, separators=(",", ":"))
    session.flush()
    return merged


# -----------------------------
# CRUD: Profiles (1-1 with users)
# -----------------------------


def set_profile(session, user_id: int, **fields) -> Profile:
    profile = session.get(Profile, user_id)
    json_keys = {
        "dietary_prefs",
        "allergies",
        "medical_conditions",
        "disabilities",
        "goals",
        "favorite_activities",
        "happy_triggers",
        "social_circle",
    }
    for k in list(fields.keys()):
        if k in json_keys:
            fields[k] = _dump_json(fields[k])
    if profile is None:
        profile = Profile(user_id=user_id, **fields)
        session.add(profile)
    else:
        for key, value in fields.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
    session.flush()
    return profile


def upsert_profile(session, user_id: int, **fields) -> Profile:
    """Alias for set_profile to make intention explicit at call sites."""
    return set_profile(session, user_id, **fields)


def get_profile(session, user_id: int, deserialize_json: bool = True) -> Optional[Dict[str, Any]]:
    profile = session.get(Profile, user_id)
    if not profile:
        return None
    result = {
        "user_id": profile.user_id,
        "dob": profile.dob,
        "sex": profile.sex,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "activity_level": profile.activity_level,
        "dietary_prefs": profile.dietary_prefs,
        "allergies": profile.allergies,
        "medical_conditions": profile.medical_conditions,
        "disabilities": profile.disabilities,
        "goals": profile.goals,
        "favorite_activities": profile.favorite_activities,
        "happy_triggers": profile.happy_triggers,
        "social_circle": profile.social_circle,
        "doctor_notes": profile.doctor_notes,
        "share_profile_with_ai": profile.share_profile_with_ai,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }
    if deserialize_json:
        for key in [
            "dietary_prefs",
            "allergies",
            "medical_conditions",
            "disabilities",
            "goals",
            "favorite_activities",
            "happy_triggers",
            "social_circle",
        ]:
            result[key] = _load_json(result[key])
    return result


def delete_profile(session, user_id: int) -> bool:
    profile = session.get(Profile, user_id)
    if not profile:
        return False
    session.delete(profile)
    session.flush()
    return True


# -----------------------------
# CRUD: Logs
# -----------------------------


def add_log(session, user_id: int, log_type: str, payload: Optional[Dict[str, Any]] = None, ts: Optional[datetime] = None) -> Log:
    entry = Log(user_id=user_id, type=log_type, payload=_dump_json(payload), ts=ts or datetime.utcnow())
    session.add(entry)
    session.flush()
    return entry


def list_logs(session, user_id: int, log_type: Optional[str] = None, limit: int = 50, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    q = session.query(Log).filter(Log.user_id == user_id)
    if log_type:
        q = q.filter(Log.type == log_type)
    if since:
        q = q.filter(Log.ts >= since)
    q = q.order_by(Log.ts.desc()).limit(limit)
    rows = q.all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "type": r.type,
            "payload": _load_json(r.payload),
            "ts": r.ts,
        }
        for r in rows
    ]


def delete_log(session, log_id: int) -> bool:
    r = session.get(Log, log_id)
    if not r:
        return False
    session.delete(r)
    session.flush()
    return True


# -----------------------------
# CRUD: Nudges
# -----------------------------


def add_nudge(session, user_id: int, category: Optional[str], title: str, body: Optional[str] = None, rationale: Optional[str] = None, accepted: Optional[bool] = None, ts: Optional[datetime] = None) -> Nudge:
    n = Nudge(
        user_id=user_id,
        category=category,
        title=title,
        body=body,
        rationale=rationale,
        accepted=accepted,
        ts=ts or datetime.utcnow(),
    )
    session.add(n)
    session.flush()
    return n


def list_nudges(session, user_id: int, category: Optional[str] = None, limit: int = 50, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    q = session.query(Nudge).filter(Nudge.user_id == user_id)
    if category:
        q = q.filter(Nudge.category == category)
    if since:
        q = q.filter(Nudge.ts >= since)
    q = q.order_by(Nudge.ts.desc()).limit(limit)
    rows = q.all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "category": r.category,
            "title": r.title,
            "body": r.body,
            "rationale": r.rationale,
            "accepted": r.accepted,
            "ts": r.ts,
        }
        for r in rows
    ]


def update_nudge(session, nudge_id: int, **fields) -> Optional[Nudge]:
    n = session.get(Nudge, nudge_id)
    if not n:
        return None
    for key, value in fields.items():
        if hasattr(n, key):
            setattr(n, key, value)
    session.flush()
    return n


def delete_nudge(session, nudge_id: int) -> bool:
    n = session.get(Nudge, nudge_id)
    if not n:
        return False
    session.delete(n)
    session.flush()
    return True


# -----------------------------
# CRUD: Rules State
# -----------------------------


def upsert_rule_state(
    session,
    user_id: int,
    rule_id: str,
    *,
    last_fired_at: Optional[datetime] = None,
    snoozed_until: Optional[datetime] = None,
    fired_on_date: Optional[date] = None,
) -> RuleState:
    rs = (
        session.query(RuleState)
        .filter(RuleState.user_id == user_id, RuleState.rule_id == rule_id)
        .one_or_none()
    )
    if rs is None:
        rs = RuleState(
            user_id=user_id,
            rule_id=rule_id,
            last_fired_at=last_fired_at,
            snoozed_until=snoozed_until,
            fired_on_date=fired_on_date,
        )
        session.add(rs)
    else:
        if last_fired_at is not None:
            rs.last_fired_at = last_fired_at
        if snoozed_until is not None:
            rs.snoozed_until = snoozed_until
        if fired_on_date is not None:
            rs.fired_on_date = fired_on_date
    session.flush()
    return rs


def get_rule_state(session, user_id: int, rule_id: str) -> Optional[RuleState]:
    return (
        session.query(RuleState)
        .filter(RuleState.user_id == user_id, RuleState.rule_id == rule_id)
        .one_or_none()
    )


def list_rule_states(session, user_id: int) -> List[RuleState]:
    return session.query(RuleState).filter(RuleState.user_id == user_id).all()


def delete_rule_state(session, rule_state_id: int) -> bool:
    rs = session.get(RuleState, rule_state_id)
    if not rs:
        return False
    session.delete(rs)
    session.flush()
    return True



