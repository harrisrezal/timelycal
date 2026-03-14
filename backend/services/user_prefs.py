import os
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def _client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_preference(telegram_user_id: int) -> dict | None:
    """Return the saved preference for a user, or None if not set."""
    result = (
        _client()
        .table("user_preferences")
        .select("preferred_station")
        .eq("telegram_user_id", telegram_user_id)
        .execute()
    )
    return result.data[0] if result.data else None


def save_preference(telegram_user_id: int, station: str) -> None:
    """Upsert the preferred station for a user."""
    _client().table("user_preferences").upsert(
        {"telegram_user_id": telegram_user_id, "preferred_station": station},
        on_conflict="telegram_user_id",
    ).execute()
