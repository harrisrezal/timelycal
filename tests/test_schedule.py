"""
Tests for services/schedule.py

Pure unit tests (no mocking):
  - _normalize_time
  - _parse_time
  - _is_towards_sf

Mocked DB tests:
  - get_next_trains
  - get_all_trains
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import time
import pytest
from freezegun import freeze_time

from services.schedule import (
    _normalize_time,
    _parse_time,
    _is_towards_sf,
    get_next_trains,
    get_all_trains,
)
from conftest import make_chunk_row


# ── _normalize_time ────────────────────────────────────────────────────────────

class TestNormalizeTime:
    def test_short_am(self):
        assert _normalize_time("7:15a") == "7:15am"

    def test_short_pm(self):
        assert _normalize_time("5:52p") == "5:52pm"

    def test_already_am(self):
        assert _normalize_time("7:15am") == "7:15am"

    def test_already_pm(self):
        assert _normalize_time("5:52pm") == "5:52pm"

    def test_strips_whitespace(self):
        assert _normalize_time("  7:15a  ") == "7:15am"

    def test_uppercase_a(self):
        assert _normalize_time("7:15A") == "7:15am"

    def test_uppercase_p(self):
        assert _normalize_time("5:52P") == "5:52pm"

    def test_midnight_edge(self):
        assert _normalize_time("12:00a") == "12:00am"

    def test_noon_edge(self):
        assert _normalize_time("12:00p") == "12:00pm"


# ── _parse_time ────────────────────────────────────────────────────────────────

class TestParseTime:
    def test_morning_time(self):
        assert _parse_time("7:15a") == time(7, 15)

    def test_afternoon_time(self):
        assert _parse_time("2:30p") == time(14, 30)

    def test_midnight(self):
        assert _parse_time("12:00a") == time(0, 0)

    def test_noon(self):
        assert _parse_time("12:00p") == time(12, 0)

    def test_invalid_returns_none(self):
        assert _parse_time("not-a-time") is None

    def test_missing_meridiem_returns_none(self):
        assert _parse_time("7:15") is None

    def test_out_of_range_returns_none(self):
        assert _parse_time("25:00am") is None

    def test_already_normalized(self):
        assert _parse_time("9:45am") == time(9, 45)


# ── _is_towards_sf ─────────────────────────────────────────────────────────────

class TestIsTowardsSF:
    def test_odd_is_northbound(self):
        assert _is_towards_sf(601) is True

    def test_even_is_southbound(self):
        assert _is_towards_sf(602) is False

    def test_smallest_odd(self):
        assert _is_towards_sf(1) is True

    def test_smallest_even(self):
        assert _is_towards_sf(2) is False

    def test_large_odd(self):
        assert _is_towards_sf(9999) is True

    def test_large_even(self):
        assert _is_towards_sf(1000) is False


# ── get_next_trains ─────────────────────────────────────────────────────────────

class TestGetNextTrains:
    def _setup_mock(self, mock_supabase, rows):
        (mock_supabase
            .table.return_value
            .select.return_value
            .ilike.return_value
            .execute.return_value
        ).data = rows

    @freeze_time("2026-03-15 09:00:00", tz_offset=-8)  # 9:00am PT
    def test_returns_trains_after_current_time(self, mock_supabase):
        rows = [
            make_chunk_row("Lawrence", [(601, "8:00a"), (603, "9:30a"), (605, "10:00a")]),
        ]
        self._setup_mock(mock_supabase, rows)
        result = get_next_trains("Lawrence", "weekday", "sf")
        times = [t["time_str"] for t in result]
        assert all("9:30" in t or "10:00" in t for t in times)
        assert len(result) <= 3

    @freeze_time("2026-03-15 09:00:00", tz_offset=-8)
    def test_filters_by_direction_sf(self, mock_supabase):
        rows = [
            make_chunk_row("Lawrence", [(601, "9:30a"), (602, "9:45a"), (603, "10:00a")]),
        ]
        self._setup_mock(mock_supabase, rows)
        result = get_next_trains("Lawrence", "weekday", "sf")
        # Only odd-numbered trains (SF direction)
        assert all(t["train"] % 2 == 1 for t in result)

    @freeze_time("2026-03-15 09:00:00", tz_offset=-8)
    def test_filters_by_direction_sj(self, mock_supabase):
        rows = [
            make_chunk_row("Lawrence", [(601, "9:30a"), (602, "9:45a"), (604, "10:00a")]),
        ]
        self._setup_mock(mock_supabase, rows)
        result = get_next_trains("Lawrence", "weekday", "sj")
        # Only even-numbered trains (SJ direction)
        assert all(t["train"] % 2 == 0 for t in result)

    @freeze_time("2026-03-16 06:00:00")  # 11pm PDT (UTC-7) — no more trains
    def test_returns_empty_when_no_trains_after_current_time(self, mock_supabase):
        rows = [
            make_chunk_row("Lawrence", [(601, "7:00a"), (603, "8:00a")]),
        ]
        self._setup_mock(mock_supabase, rows)
        result = get_next_trains("Lawrence", "weekday", "sf")
        assert result == []

    @freeze_time("2026-03-15 09:00:00", tz_offset=-8)
    def test_deduplicates_train_numbers(self, mock_supabase):
        # Same train 601 appears in two rows
        rows = [
            make_chunk_row("Lawrence", [(601, "9:30a")], row_id=1),
            make_chunk_row("Lawrence", [(601, "9:30a")], row_id=2),
        ]
        self._setup_mock(mock_supabase, rows)
        result = get_next_trains("Lawrence", "weekday", "sf")
        train_nums = [t["train"] for t in result]
        assert len(train_nums) == len(set(train_nums))

    @freeze_time("2026-03-15 09:00:00", tz_offset=-8)
    def test_respects_n_limit(self, mock_supabase):
        rows = [
            make_chunk_row("Lawrence", [(601, "9:15a"), (603, "9:30a"), (605, "9:45a"), (607, "10:00a")]),
        ]
        self._setup_mock(mock_supabase, rows)
        result = get_next_trains("Lawrence", "weekday", "sf", n=2)
        assert len(result) <= 2


# ── get_all_trains ──────────────────────────────────────────────────────────────

class TestGetAllTrains:
    def _setup_mock(self, mock_supabase, rows):
        (mock_supabase
            .table.return_value
            .select.return_value
            .ilike.return_value
            .execute.return_value
        ).data = rows

    def test_returns_all_trains_sorted(self, mock_supabase):
        rows = [
            make_chunk_row("Lawrence", [(603, "9:45a"), (601, "7:15a"), (605, "11:00a")]),
        ]
        self._setup_mock(mock_supabase, rows)
        result = get_all_trains("Lawrence", "weekday", "sf")
        times = [t["time"] for t in result]
        assert times == sorted(times)

    def test_no_time_filter_returns_all(self, mock_supabase):
        rows = [
            make_chunk_row("Lawrence", [(601, "5:00a"), (603, "11:00p")]),
        ]
        self._setup_mock(mock_supabase, rows)
        result = get_all_trains("Lawrence", "weekday", "sf")
        assert len(result) == 2

    def test_returns_empty_for_no_matching_rows(self, mock_supabase):
        self._setup_mock(mock_supabase, [])
        result = get_all_trains("Lawrence", "weekday", "sf")
        assert result == []
