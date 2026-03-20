"""
Tests for services/user_prefs.py

Mocked Supabase tests — no live DB calls.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from services.user_prefs import get_preference, save_preference


class TestGetPreference:
    def test_returns_preference_when_user_exists(self, mock_supabase):
        (mock_supabase
            .table.return_value
            .select.return_value
            .eq.return_value
            .execute.return_value
        ).data = [{"telegram_user_id": 123, "preferred_station": "Lawrence"}]

        result = get_preference(123)
        assert result == {"telegram_user_id": 123, "preferred_station": "Lawrence"}

    def test_returns_none_when_user_not_found(self, mock_supabase):
        (mock_supabase
            .table.return_value
            .select.return_value
            .eq.return_value
            .execute.return_value
        ).data = []

        result = get_preference(999)
        assert result is None

    def test_queries_correct_table(self, mock_supabase):
        (mock_supabase
            .table.return_value
            .select.return_value
            .eq.return_value
            .execute.return_value
        ).data = []

        get_preference(123)
        mock_supabase.table.assert_called_with("user_preferences")

    def test_filters_by_user_id(self, mock_supabase):
        mock_chain = mock_supabase.table.return_value.select.return_value
        mock_chain.eq.return_value.execute.return_value.data = []

        get_preference(456)
        mock_chain.eq.assert_called_with("telegram_user_id", 456)


class TestSavePreference:
    def test_upserts_correct_payload(self, mock_supabase):
        mock_upsert = (mock_supabase
            .table.return_value
            .upsert.return_value
            .execute)
        mock_upsert.return_value.data = []

        save_preference(123, "Lawrence")

        mock_supabase.table.return_value.upsert.assert_called_once()
        call_args = mock_supabase.table.return_value.upsert.call_args
        payload = call_args[0][0]
        assert payload["telegram_user_id"] == 123
        assert payload["preferred_station"] == "Lawrence"

    def test_upserts_to_correct_table(self, mock_supabase):
        (mock_supabase
            .table.return_value
            .upsert.return_value
            .execute.return_value
        ).data = []

        save_preference(123, "Palo Alto")
        mock_supabase.table.assert_called_with("user_preferences")

    def test_uses_on_conflict_for_upsert(self, mock_supabase):
        (mock_supabase
            .table.return_value
            .upsert.return_value
            .execute.return_value
        ).data = []

        save_preference(123, "Lawrence")
        call_kwargs = mock_supabase.table.return_value.upsert.call_args[1]
        assert call_kwargs.get("on_conflict") == "telegram_user_id"
