import os
import re
from datetime import datetime, timedelta
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


# Gilroy extension stops not included in the scheduling STATIONS list
_EXTENSION_STATIONS = [
    "Blossom Hill",
    "Capitol",
    "Morgan Hill",
    "San Martin",
    "Gilroy",
]

_TRAIN_NUM_RE = re.compile(r'[Tt]rain\s+(\d{3,4})')

# Operational noise — not useful to commuters
_SKIP_ALERT_PREFIXES = ["track change", "equipment change"]

_DIRECTION_SUBS = [
    (re.compile(r'\bnorthbound\b', re.IGNORECASE), 'towards San Francisco'),
    (re.compile(r'\bsouthbound\b', re.IGNORECASE), 'towards San Jose'),
]


def _humanise_directions(text: str) -> str:
    for pattern, replacement in _DIRECTION_SUBS:
        text = pattern.sub(replacement, text)
    return text


def _is_unwanted_alert(header: str) -> bool:
    lower = header.lower()
    return any(lower.startswith(p) for p in _SKIP_ALERT_PREFIXES)


def _extract_train_numbers(text: str) -> list[str]:
    """Return all train numbers mentioned in the text."""
    return _TRAIN_NUM_RE.findall(text)


def _lookup_train_stations(train_num: str) -> list[str]:
    """Query Supabase documents for all stations that train_num serves."""
    try:
        rows = (
            _client()
            .table("documents")
            .select("content")
            .ilike("content", f"%{train_num}:%")
            .execute()
        ).data
        stations = []
        for row in rows:
            m = re.match(r'Info:\s*([^|]+)', row.get("content", ""))
            if m:
                name = m.group(1).strip()
                if name and name not in stations:
                    stations.append(name)
        return stations
    except Exception:
        return []


def _get_train_stop_time(train_num: str, station: str) -> str | None:
    """Return scheduled departure time for train_num at station, or None."""
    try:
        rows = (
            _client()
            .table("documents")
            .select("content")
            .ilike("content", f"%{station}%")
            .execute()
        ).data
        station_rows = [
            r for r in rows
            if re.search(
                rf'Info:\s*{re.escape(station)}\s*(?:\||$)',
                r.get("content", ""),
                re.IGNORECASE,
            )
        ]
        train_pattern = re.compile(
            rf'\b{re.escape(train_num)}:\s*(\d{{1,2}}:\d{{2}}[apm]+)',
            re.IGNORECASE,
        )
        for row in station_rows:
            m = train_pattern.search(row["content"])
            if m:
                return m.group(1)
        return None
    except Exception:
        return None


def _extract_delay_info(text: str) -> tuple[str, int] | None:
    """Extract delay from alert text. Returns (display_label, minutes) or None.
    Handles ranges: '35-40 minutes late' → ('35-40 min', 37).
    """
    m = re.search(r'(\d+)(?:-(\d+))?\s+minutes?\s+late', text, re.IGNORECASE)
    if not m:
        return None
    lo = int(m.group(1))
    if m.group(2):
        hi = int(m.group(2))
        return (f"{lo}-{hi} min", (lo + hi) // 2)
    return (f"{lo} min", lo)


def _add_minutes(time_str: str, minutes: int) -> str:
    """Add minutes to a time string like '6:46am' and return the new time string."""
    m = re.match(r'(\d{1,2}):(\d{2})(am|pm)', time_str, re.IGNORECASE)
    if not m:
        return time_str
    hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    dt = datetime(2000, 1, 1, hour, minute) + timedelta(minutes=minutes)
    new_meridiem = "am" if dt.hour < 12 else "pm"
    display_hour = dt.hour % 12 or 12
    return f"{display_hour}:{dt.minute:02d}{new_meridiem}"


def _extract_stations(text: str) -> list[str]:
    """Return Caltrain station names mentioned in text, including via train number lookup."""
    from services.schedule import STATIONS
    all_stations = STATIONS + _EXTENSION_STATIONS
    found = [s for s in all_stations if s.lower() in text.lower()]
    for train_num in _extract_train_numbers(text):
        for station in _lookup_train_stations(train_num):
            if station not in found:
                found.append(station)
    return found


def fetch_511_alerts() -> list[dict]:
    """
    Fetch real-time Caltrain service alerts from the 511 SF Bay API.
    Returns a list of {id, text, source, stations} dicts.
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
            if header and not _is_unwanted_alert(header):
                text = f"🚨 Caltrain Alert\n\n{header}"
                if desc and desc != header:
                    text += f"\n\n{desc}"
                text = _humanise_directions(text)
                alerts.append({
                    "id": alert_id,
                    "text": text,
                    "source": "511",
                    "stations": _extract_stations(header + " " + desc),
                })
        return alerts
    except Exception:
        return []


def fetch_rss_alerts() -> list[dict]:
    """
    Fetch Caltrain news and planned service changes from the official RSS feed.
    Returns a list of {id, text, source, stations} dicts.
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
                text = _humanise_directions(text)
                alerts.append({
                    "id": alert_id,
                    "text": text,
                    "source": "rss",
                    "stations": _extract_stations(title + " " + summary),
                })
        return alerts
    except Exception:
        return []


def get_new_alerts() -> list[dict]:
    """
    Fetch alerts from 511 API and RSS feed, filter out already-seen ones,
    mark new ones as seen, and return them as structured dicts.
    Each dict: {id, text, source, stations}
    """
    all_alerts = fetch_511_alerts() + fetch_rss_alerts()
    new_alerts = []
    for alert in all_alerts:
        if not _is_seen(alert["id"]):
            _mark_seen(alert["id"])
            new_alerts.append(alert)
    return new_alerts
