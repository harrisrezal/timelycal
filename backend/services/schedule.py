import os
import re
from datetime import datetime, time
import pytz

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
PACIFIC = pytz.timezone("America/Los_Angeles")

# Caltrain stations in geographic order SF → San Jose
STATIONS = [
    "San Francisco",
    "22nd Street",
    "Bayshore",
    "S. San Francisco",
    "San Bruno",
    "Millbrae",
    "Broadway",
    "Burlingame",
    "San Mateo",
    "Hayward Park",
    "Hillsdale",
    "Belmont",
    "San Carlos",
    "Redwood City",
    "Menlo Park",
    "Palo Alto",
    "California Avenue",
    "San Antonio",
    "Mountain View",
    "Sunnyvale",
    "Lawrence",
    "Santa Clara",
    "College Park",
    "San Jose Diridon",
    "Tamien",
]

# Match "601: 7:15a" — 3-4 digit train number followed by a time
_TRAIN_TIME_RE = re.compile(r"\b(\d{3,4}):\s*(\d{1,2}:\d{2}[apm]+)", re.IGNORECASE)


def _normalize_time(t: str) -> str:
    """'4:54a' → '4:54am', '5:52p' → '5:52pm'."""
    t = t.lower().strip()
    if t.endswith("a") and not t.endswith("am"):
        t += "m"
    elif t.endswith("p") and not t.endswith("pm"):
        t += "m"
    return t


def _parse_time(t: str) -> time | None:
    try:
        return datetime.strptime(_normalize_time(t), "%I:%M%p").time()
    except ValueError:
        return None


def _is_towards_sf(train_number: int) -> bool:
    """True = train goes towards San Francisco (northbound). Odd train numbers."""
    return train_number % 2 == 1


def _train_label(train_number: int) -> str:
    """Return a service type label for display. 4xx = Limited, 5xx = Express."""
    if 400 <= train_number <= 499:
        return " [Limited]"
    if 500 <= train_number <= 599:
        return " [Express]"
    return ""


def get_next_trains(
    station: str, day_type: str, direction: str, n: int = 3
) -> list[dict]:
    """
    Return the next n trains from `station` after current Pacific time.
    day_type: 'weekday' or 'weekend'
    direction: 'sj' (towards San Jose) or 'sf' (towards San Francisco)

    Chunk format in DB: "Info: Mountain View | 601: 7:15a | 603: 7:45a | ..."
    Each chunk = one station row from the PDF table.
    Train numbers are 3-4 digit keys; times follow immediately after the colon.
    """
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    rows = (
        client.table("documents")
        .select("id, content, metadata")
        .ilike("content", f"%{station}%")
        .execute()
    ).data
    rows = [
        r for r in rows
        if day_type in r.get("metadata", {}).get("source", "").lower()
        and re.search(rf':\s*{re.escape(station)}\s*(?:\||$)', r["content"], re.IGNORECASE)
    ]

    now = datetime.now(PACIFIC).time()
    want_sf = direction == "sf"

    seen_trains: set[int] = set()
    candidates = []

    for row in rows:
        for m in _TRAIN_TIME_RE.finditer(row["content"]):
            train_num = int(m.group(1))
            if train_num in seen_trains:
                continue
            if _is_towards_sf(train_num) != want_sf:
                continue
            dep_time = _parse_time(m.group(2))
            if dep_time is None:
                continue
            if dep_time >= now:
                seen_trains.add(train_num)
                time_str = dep_time.strftime("%I:%M%p").lstrip("0").lower()
                candidates.append({"train": train_num, "time": dep_time, "time_str": time_str})

    candidates.sort(key=lambda c: c["time"])
    return candidates[:n]


def _extract_train_times(station: str, day_type: str) -> dict[int, time]:
    """
    Query DB for chunks matching station+day_type and return {train_num: departure_time}.
    Used internally by get_travel_times().
    """
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    rows = (
        client.table("documents")
        .select("id, content, metadata")
        .ilike("content", f"%{station}%")
        .execute()
    ).data
    rows = [
        r for r in rows
        if day_type in r.get("metadata", {}).get("source", "").lower()
        and re.search(rf':\s*{re.escape(station)}\s*(?:\||$)', r["content"], re.IGNORECASE)
    ]

    times: dict[int, time] = {}
    for row in rows:
        for m in _TRAIN_TIME_RE.finditer(row["content"]):
            train_num = int(m.group(1))
            if train_num not in times:
                t = _parse_time(m.group(2))
                if t is not None:
                    times[train_num] = t
    return times


def get_travel_times(from_station: str, to_station: str, day_type: str) -> list[dict]:
    """
    Return travel times for all trains serving both stations on the given day.
    Direction is inferred automatically from the STATIONS geographic order.

    Each result dict: {"train": int, "depart": time, "depart_str": str,
                       "arrive": time, "arrive_str": str, "duration_mins": int, "label": str}
    Sorted by departure time.
    """
    from_idx = STATIONS.index(from_station)
    to_idx = STATIONS.index(to_station)
    want_sf = to_idx < from_idx  # travelling towards SF if destination is earlier in list

    from_times = _extract_train_times(from_station, day_type)
    to_times = _extract_train_times(to_station, day_type)

    results = []
    for train_num, depart in from_times.items():
        if _is_towards_sf(train_num) != want_sf:
            continue
        if train_num not in to_times:
            continue
        arrive = to_times[train_num]
        duration = (arrive.hour * 60 + arrive.minute) - (depart.hour * 60 + depart.minute)
        if duration < 0:
            continue  # data anomaly — skip
        depart_str = depart.strftime("%I:%M%p").lstrip("0").lower()
        arrive_str = arrive.strftime("%I:%M%p").lstrip("0").lower()
        results.append({
            "train": train_num,
            "depart": depart,
            "depart_str": depart_str,
            "arrive": arrive,
            "arrive_str": arrive_str,
            "duration_mins": duration,
            "label": _train_label(train_num),
        })

    results.sort(key=lambda r: r["depart"])
    return results


def get_all_trains(station: str, day_type: str, direction: str) -> list[dict]:
    """Return ALL trains for a station/day_type/direction sorted by departure time."""
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    rows = (
        client.table("documents")
        .select("id, content, metadata")
        .ilike("content", f"%{station}%")
        .execute()
    ).data
    rows = [
        r for r in rows
        if day_type in r.get("metadata", {}).get("source", "").lower()
        and re.search(rf':\s*{re.escape(station)}\s*(?:\||$)', r["content"], re.IGNORECASE)
    ]

    want_sf = direction == "sf"
    seen_trains: set[int] = set()
    candidates = []

    for row in rows:
        for m in _TRAIN_TIME_RE.finditer(row["content"]):
            train_num = int(m.group(1))
            if train_num in seen_trains:
                continue
            if _is_towards_sf(train_num) != want_sf:
                continue
            dep_time = _parse_time(m.group(2))
            if dep_time is None:
                continue
            seen_trains.add(train_num)
            time_str = dep_time.strftime("%I:%M%p").lstrip("0").lower()
            candidates.append({"train": train_num, "time": dep_time, "time_str": time_str})

    candidates.sort(key=lambda c: c["time"])
    return candidates
