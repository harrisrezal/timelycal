import os
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def _client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def subscribe(platform: str, platform_id: str, alert_tier: str = "both", station: str | None = None) -> None:
    """Upsert subscription — creates new row or updates existing preferences."""
    _client().table("subscriptions").upsert(
        {
            "platform": platform,
            "platform_id": str(platform_id),
            "alert_tier": alert_tier,
            "station": station,
        },
        on_conflict="platform,platform_id",
    ).execute()


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


def get_subscription(platform: str, platform_id: str) -> dict | None:
    """Return the subscription row for a user, or None if not subscribed."""
    result = (
        _client()
        .table("subscriptions")
        .select("*")
        .eq("platform", platform)
        .eq("platform_id", str(platform_id))
        .execute()
    )
    return result.data[0] if result.data else None


def get_telegram_subscribers() -> list[dict]:
    """Return all Telegram subscriptions with their preferences."""
    rows = (
        _client()
        .table("subscriptions")
        .select("platform_id, alert_tier, station")
        .eq("platform", "telegram")
        .execute()
    )
    return rows.data
