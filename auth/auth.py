from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: int
    email: str
    display_name: str


def get_current_user() -> Optional[User]:
    """Placeholder for Streamlit session-based user retrieval."""
    return None


