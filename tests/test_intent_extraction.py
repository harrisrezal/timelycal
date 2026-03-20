"""
Tests for services/rag.py :: extract_intent()

All tests mock the Gemini API — no live calls.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import json
import pytest
from unittest.mock import MagicMock, patch

from services.rag import extract_intent, _INTENT_FALLBACK


def _mock_gemini(response_text: str):
    """Return a mock genai.Client whose generate_content returns response_text."""
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


def _intent_json(**kwargs) -> str:
    base = {
        "station": None,
        "direction": None,
        "day_type": "weekday",
        "query_type": "general",
        "time_context": None,
    }
    base.update(kwargs)
    return json.dumps(base)


class TestExtractIntentValid:
    def test_station_extracted(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Lawrence", direction="sf", query_type="next_train")
        ))
        result = extract_intent("next train from Lawrence to SF")
        assert result["station"] == "Lawrence"

    def test_direction_sf(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Palo Alto", direction="sf", query_type="next_train")
        ))
        result = extract_intent("next northbound train from Palo Alto")
        assert result["direction"] == "sf"

    def test_direction_sj(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Mountain View", direction="sj", query_type="next_train")
        ))
        result = extract_intent("trains towards San Jose from Mountain View")
        assert result["direction"] == "sj"

    def test_query_type_first_train(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Lawrence", direction="sf", query_type="first_train")
        ))
        result = extract_intent("what is the first train from Lawrence to SF?")
        assert result["query_type"] == "first_train"

    def test_query_type_last_train(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="San Jose Diridon", direction="sf", query_type="last_train")
        ))
        result = extract_intent("last train from San Jose Diridon tonight")
        assert result["query_type"] == "last_train"

    def test_query_type_next_train(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Sunnyvale", direction="sf", query_type="next_train")
        ))
        result = extract_intent("next train from Sunnyvale")
        assert result["query_type"] == "next_train"

    def test_query_type_full_schedule(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Redwood City", direction=None, query_type="full_schedule")
        ))
        result = extract_intent("show me the full schedule for Redwood City")
        assert result["query_type"] == "full_schedule"

    def test_weekend_day_type(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Palo Alto", day_type="weekend", query_type="next_train")
        ))
        result = extract_intent("next train from Palo Alto on Saturday")
        assert result["day_type"] == "weekend"

    def test_time_context_morning(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Lawrence", time_context="morning", query_type="next_train")
        ))
        result = extract_intent("morning trains from Lawrence to SF")
        assert result["time_context"] == "morning"

    def test_no_station_returns_none(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station=None, query_type="general")
        ))
        result = extract_intent("how many stops between SF and SJ?")
        assert result["station"] is None

    def test_returns_all_required_keys(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            _intent_json(station="Lawrence", direction="sf", query_type="next_train")
        ))
        result = extract_intent("next train from Lawrence")
        for key in _INTENT_FALLBACK:
            assert key in result


class TestExtractIntentFallback:
    def test_invalid_json_returns_fallback(self, mocker):
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(
            "This is not JSON at all"
        ))
        result = extract_intent("next train")
        assert result == dict(_INTENT_FALLBACK)

    def test_gemini_exception_returns_fallback(self, mocker):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API error")
        mocker.patch("services.rag.genai.Client", return_value=mock_client)
        result = extract_intent("next train")
        assert result == dict(_INTENT_FALLBACK)

    def test_markdown_wrapped_json_parsed_correctly(self, mocker):
        wrapped = "```json\n" + _intent_json(station="Lawrence", direction="sf", query_type="next_train") + "\n```"
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(wrapped))
        result = extract_intent("next train from Lawrence to SF")
        assert result["station"] == "Lawrence"
        assert result["direction"] == "sf"

    def test_missing_key_filled_with_fallback(self, mocker):
        # Gemini returns JSON missing "time_context"
        partial = {"station": "Lawrence", "direction": "sf", "day_type": "weekday", "query_type": "next_train"}
        mocker.patch("services.rag.genai.Client", return_value=_mock_gemini(json.dumps(partial)))
        result = extract_intent("next train from Lawrence")
        assert "time_context" in result
        assert result["time_context"] is None
