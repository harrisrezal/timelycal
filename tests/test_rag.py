"""
Tests for services/rag.py

Unit tests: _text_search (mocked Supabase)
Integration tests: query() with golden queries — marked @pytest.mark.integration
                   These hit live Supabase + Gemini. Run with: pytest -m integration
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import json
import pytest
from unittest.mock import MagicMock

from services.rag import _text_search


# ── _text_search ───────────────────────────────────────────────────────────────

class TestTextSearch:
    def _make_client(self, rows_per_keyword):
        """Build a mock Supabase client where each ilike call returns the given rows."""
        client = MagicMock()
        client.table.return_value.select.return_value.ilike.return_value.execute.return_value.data = rows_per_keyword
        return client

    def test_returns_results_for_single_keyword(self):
        rows = [{"id": 1, "content": "Info: Lawrence | 601: 7:15a", "metadata": {}}]
        client = self._make_client(rows)
        result = _text_search(client, ["lawrence"])
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_deduplicates_across_keywords(self):
        row = {"id": 1, "content": "Info: Lawrence | 601: 7:15a", "metadata": {}}
        client = self._make_client([row])
        # Same row returned for both keywords — should only appear once
        result = _text_search(client, ["lawrence", "train"])
        assert len(result) == 1

    def test_empty_keywords_returns_empty(self):
        client = MagicMock()
        result = _text_search(client, [])
        assert result == []
        client.table.assert_not_called()

    def test_merges_unique_results_across_keywords(self):
        def ilike_side_effect(*args, **kwargs):
            # args[1] is the pattern e.g. "%lawrence%"
            pattern = args[1]
            mock_chain = MagicMock()
            if "lawrence" in pattern:
                mock_chain.execute.return_value.data = [{"id": 1, "content": "Lawrence chunk", "metadata": {}}]
            else:
                mock_chain.execute.return_value.data = [{"id": 2, "content": "Sunnyvale chunk", "metadata": {}}]
            return mock_chain

        client = MagicMock()
        client.table.return_value.select.return_value.ilike.side_effect = ilike_side_effect
        result = _text_search(client, ["lawrence", "sunnyvale"])
        ids = {r["id"] for r in result}
        assert ids == {1, 2}

    def test_no_results_returns_empty(self):
        client = self._make_client([])
        result = _text_search(client, ["nonexistent"])
        assert result == []


# ── Golden / Integration tests ─────────────────────────────────────────────────

def load_golden_queries():
    path = os.path.join(os.path.dirname(__file__), "golden_queries.json")
    with open(path) as f:
        return json.load(f)


@pytest.mark.integration
@pytest.mark.parametrize("case", load_golden_queries())
def test_rag_golden(case):
    """
    Integration test: runs the full RAG pipeline against live Supabase + Gemini.
    Asserts that each expected keyword appears in the response.

    Run with: pytest -m integration
    Skip in CI unit test runs: pytest -m "not integration"
    """
    from services.rag import query
    answer = query(case["question"])
    assert isinstance(answer, str)
    assert len(answer) > 0
    for keyword in case.get("must_contain", []):
        assert keyword.lower() in answer.lower(), (
            f"Expected '{keyword}' in answer for question: {case['question']}\n"
            f"Got: {answer}"
        )
