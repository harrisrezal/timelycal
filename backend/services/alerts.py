import os
import httpx
import feedparser
from supabase import create_client

API_511_KEY = os.environ.get("API_511_KEY")
ALERTS_511_URL = "https://api.511.org/transit/servicealerts"
RSS_URL = "https://www.caltrain.com/feed/caltrain_news.rss"


def _client():
    return create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))


def _is_seen(alert_id: str) -> bool:
    result = (
        _client()
        .table("seen_alerts")
        .select("alert_id")
        .eq("alert_id", alert_id)
        .execute()
    )
    return bool(result.data)


def _mark_seen(alert_id: str) -> None:
    _client().table("seen_alerts").upsert({"alert_id": alert_id}).execute()


def fetch_511_alerts() -> list[dict]:
    """
    Fetch real-time Caltrain service alerts from the 511 SF Bay API.
    Returns a list of {id, text} dicts for new alerts.
    """
    try:
        resp = httpx.get(
            ALERTS_511_URL,
            params={"api_key": API_511_KEY, "agency": "CT", "format": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        alerts = []
        for entity in data.get("Entities", []):
            alert = entity.get("Alert", {})
            alert_id = f"511_{entity.get('Id', '')}"
            translations = alert.get("HeaderText", {}).get("Translations") or [{}]
            header = translations[0].get("Text", "")
            desc_translations = alert.get("DescriptionText", {}).get("Translations") or [{}]
            desc = desc_translations[0].get("Text", "")
            if header:
                text = f"🚨 Caltrain Alert\n\n{header}"
                if desc and desc != header:
                    text += f"\n\n{desc}"
                alerts.append({"id": alert_id, "text": text})
        return alerts
    except Exception:
        return []


def fetch_rss_alerts() -> list[dict]:
    """
    Fetch Caltrain news and planned service changes from the official RSS feed.
    Returns a list of {id, text} dicts.
    """
    try:
        feed = feedparser.parse(RSS_URL)
        alerts = []
        for entry in feed.entries:
            alert_id = f"rss_{entry.get('id') or entry.get('link', '')}"
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            if title:
                text = f"📢 Caltrain News\n\n{title}"
                if summary and summary != title:
                    text += f"\n\n{summary}"
                alerts.append({"id": alert_id, "text": text})
        return alerts
    except Exception:
        return []


def get_new_alerts() -> list[str]:
    """
    Fetch alerts from 511 API and RSS feed, filter out already-seen ones,
    mark new ones as seen, and return their message texts.
    """
    all_alerts = fetch_511_alerts() + fetch_rss_alerts()
    new_messages = []
    for alert in all_alerts:
        if not _is_seen(alert["id"]):
            _mark_seen(alert["id"])
            new_messages.append(alert["text"])
    return new_messages
