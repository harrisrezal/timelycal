import os
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def _client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def subscribe(platform: str, platform_id: str) -> bool:
    """
    Subscribe a user to Caltrain alerts.
    Returns True if newly subscribed, False if already subscribed.
    """
    existing = (
        _client()
        .table("subscriptions")
        .select("id")
        .eq("platform", platform)
        .eq("platform_id", str(platform_id))
        .execute()
    )
    if existing.data:
        return False
    _client().table("subscriptions").insert(
        {"platform": platform, "platform_id": str(platform_id)}
    ).execute()
    return True


def unsubscribe(platform: str, platform_id: str) -> bool:
    """
    Unsubscribe a user from Caltrain alerts.
    Returns True if removed, False if wasn't subscribed.
    """
    result = (
        _client()
        .table("subscriptions")
        .delete()
        .eq("platform", platform)
        .eq("platform_id", str(platform_id))
        .execute()
    )
    return bool(result.data)


def get_telegram_subscribers() -> list[int]:
    """Return all Telegram chat IDs currently subscribed to alerts."""
    rows = (
        _client()
        .table("subscriptions")
        .select("platform_id")
        .eq("platform", "telegram")
        .execute()
    )
    return [int(r["platform_id"]) for r in rows.data]
