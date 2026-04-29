import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from unittest.mock import MagicMock, patch

from services.alerts import (
    _extract_train_numbers,
    _lookup_train_stations,
    _get_train_stop_time,
    _extract_stations,
    _extract_delay_info,
    _add_minutes,
    _is_unwanted_alert,
    _humanise_directions,
)


def _mock_client(rows):
    mock = MagicMock()
    (mock.table.return_value
         .select.return_value
         .ilike.return_value
         .execute.return_value).data = rows
    return mock


class TestExtractTrainNumbers:
    def test_single_train(self):
        assert _extract_train_numbers("Train 420 Southbound Is Running Late") == ["420"]

    def test_multiple_trains(self):
        assert _extract_train_numbers("Train 420 and Train 601 affected") == ["420", "601"]

    def test_no_train(self):
        assert _extract_train_numbers("No trains mentioned") == []

    def test_lowercase_train(self):
        assert _extract_train_numbers("train 603 delayed") == ["603"]

    def test_three_digit_train(self):
        assert _extract_train_numbers("Train 101 delayed") == ["101"]

    def test_four_digit_train(self):
        assert _extract_train_numbers("Train 1234 delayed") == ["1234"]


class TestLookupTrainStations:
    def test_returns_stations_from_rows(self):
        rows = [
            {"content": "Info: Lawrence | 420: 2:10pm | 601: 7:15am"},
            {"content": "Info: Mountain View | 420: 2:05pm | 601: 7:10am"},
        ]
        with patch("services.alerts._client", return_value=_mock_client(rows)):
            result = _lookup_train_stations("420")
        assert "Lawrence" in result
        assert "Mountain View" in result

    def test_returns_empty_when_no_rows(self):
        with patch("services.alerts._client", return_value=_mock_client([])):
            result = _lookup_train_stations("999")
        assert result == []

    def test_deduplicates_stations(self):
        rows = [
            {"content": "Info: Lawrence | 420: 2:10pm"},
            {"content": "Info: Lawrence | 420: 2:10pm"},
        ]
        with patch("services.alerts._client", return_value=_mock_client(rows)):
            result = _lookup_train_stations("420")
        assert result.count("Lawrence") == 1

    def test_returns_empty_on_exception(self):
        mock = MagicMock()
        mock.table.side_effect = Exception("DB error")
        with patch("services.alerts._client", return_value=mock):
            result = _lookup_train_stations("420")
        assert result == []


class TestGetTrainStopTime:
    def test_returns_time_for_matching_train(self):
        rows = [{"content": "Info: Lawrence | 420: 2:10pm | 601: 7:15am"}]
        with patch("services.alerts._client", return_value=_mock_client(rows)):
            result = _get_train_stop_time("420", "Lawrence")
        assert result == "2:10pm"

    def test_returns_none_when_train_not_in_row(self):
        rows = [{"content": "Info: Lawrence | 601: 7:15am"}]
        with patch("services.alerts._client", return_value=_mock_client(rows)):
            result = _get_train_stop_time("420", "Lawrence")
        assert result is None

    def test_returns_none_when_no_rows(self):
        with patch("services.alerts._client", return_value=_mock_client([])):
            result = _get_train_stop_time("420", "Lawrence")
        assert result is None

    def test_returns_none_on_exception(self):
        mock = MagicMock()
        mock.table.side_effect = Exception("DB error")
        with patch("services.alerts._client", return_value=mock):
            result = _get_train_stop_time("420", "Lawrence")
        assert result is None


class TestExtractStations:
    def test_direct_name_match_still_works(self):
        result = _extract_stations("Train delayed at Lawrence station")
        assert "Lawrence" in result

    def test_train_number_triggers_lookup(self):
        with patch("services.alerts._lookup_train_stations", return_value=["Lawrence", "Mountain View"]):
            result = _extract_stations("Train 420 Southbound Is Running Late")
        assert "Lawrence" in result
        assert "Mountain View" in result

    def test_no_match_returns_empty(self):
        with patch("services.alerts._lookup_train_stations", return_value=[]):
            result = _extract_stations("Service disruption on the line")
        assert result == []

    def test_deduplicates_direct_and_lookup(self):
        with patch("services.alerts._lookup_train_stations", return_value=["Lawrence", "Mountain View"]):
            result = _extract_stations("Train 420 delayed at Lawrence")
        assert result.count("Lawrence") == 1

    def test_extension_station_matched_directly(self):
        result = _extract_stations("Delay at San Martin station")
        assert "San Martin" in result


class TestExtractDelayInfo:
    def test_single_value(self):
        assert _extract_delay_info("Train 107 is running about 12 minutes late") == ("12 min", 12)

    def test_range_value(self):
        label, mins = _extract_delay_info("Train 420 is running about 35-40 minutes late")
        assert label == "35-40 min"
        assert mins == 37

    def test_no_delay_returns_none(self):
        assert _extract_delay_info("Train 420 Southbound Is Running Late") is None

    def test_case_insensitive(self):
        assert _extract_delay_info("running 5 Minutes Late") == ("5 min", 5)


class TestAddMinutes:
    def test_simple_addition(self):
        assert _add_minutes("6:46am", 12) == "6:58am"

    def test_crosses_hour(self):
        assert _add_minutes("6:55am", 10) == "7:05am"

    def test_crosses_noon(self):
        assert _add_minutes("11:50am", 15) == "12:05pm"

    def test_pm_time(self):
        assert _add_minutes("2:10pm", 37) == "2:47pm"

    def test_range_midpoint(self):
        assert _add_minutes("6:46am", 37) == "7:23am"

    def test_invalid_format_returns_original(self):
        assert _add_minutes("unknown", 10) == "unknown"


class TestIsUnwantedAlert:
    def test_track_change_filtered(self):
        assert _is_unwanted_alert("Track Change: Train 168 will Arrive and Depart off Track 9") is True

    def test_equipment_change_filtered(self):
        assert _is_unwanted_alert("Equipment Change: Train 420 will operate with fewer cars") is True

    def test_platform_change_filtered(self):
        assert _is_unwanted_alert("Platform Change: Train 123 will Depart off Track 8 at San Jose Diridon") is True

    def test_case_insensitive(self):
        assert _is_unwanted_alert("track change: some alert") is True
        assert _is_unwanted_alert("equipment change: some alert") is True
        assert _is_unwanted_alert("platform change: some alert") is True

    def test_delay_not_filtered(self):
        assert _is_unwanted_alert("Delayed: Train 420 Is Running 35-40 Minutes Late") is False

    def test_cancellation_not_filtered(self):
        assert _is_unwanted_alert("Cancelled: Train 101 will not operate today") is False

    def test_early_departure_not_filtered(self):
        assert _is_unwanted_alert("Early Departure: Train 422 will depart 5 minutes early") is False


class TestHumaniseDirections:
    def test_southbound_replaced(self):
        assert _humanise_directions("Train 112 southbound") == "Train 112 towards San Jose"

    def test_northbound_replaced(self):
        assert _humanise_directions("Train 101 northbound") == "Train 101 towards San Francisco"

    def test_case_insensitive(self):
        assert _humanise_directions("Train 112 Southbound") == "Train 112 towards San Jose"
        assert _humanise_directions("Train 101 Northbound") == "Train 101 towards San Francisco"

    def test_no_direction_unchanged(self):
        assert _humanise_directions("Train 112 is delayed") == "Train 112 is delayed"

    def test_both_directions_in_text(self):
        result = _humanise_directions("northbound trains and southbound trains")
        assert "towards San Francisco" in result
        assert "towards San Jose" in result
