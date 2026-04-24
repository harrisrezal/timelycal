import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from unittest.mock import MagicMock, patch

from services.alerts import (
    _extract_train_numbers,
    _lookup_train_stations,
    _get_train_stop_time,
    _extract_stations,
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
