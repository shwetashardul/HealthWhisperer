from typing import List


def record_nudge(action: str) -> None:
    # Placeholder: would insert into DB
    _ = action


def list_nudges(limit: int = 5) -> List[str]:
    return [
        "Sip water",
        "Stand and stretch",
        "Mindful breath for 60s",
    ][:limit]


