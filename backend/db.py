import os
from datetime import datetime, timezone

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def _client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def save_user(chat_id: int, username: str | None) -> None:
    """Insert user on first visit; update last_seen + username on subsequent visits."""
    now = datetime.now(timezone.utc).isoformat()
    client = _client()

    existing = (
        client.table("users")
        .select("chat_id")
        .eq("chat_id", chat_id)
        .execute()
    )

    if existing.data:
        client.table("users").update(
            {"last_seen": now, "username": username}
        ).eq("chat_id", chat_id).execute()
    else:
        client.table("users").insert(
            {
                "chat_id": chat_id,
                "username": username,
                "first_seen": now,
                "last_seen": now,
            }
        ).execute()


def get_user_count() -> int:
    """Return total number of unique users."""
    result = _client().table("users").select("chat_id", count="exact").execute()
    return result.count or 0
