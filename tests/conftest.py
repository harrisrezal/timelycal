import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_supabase(mocker):
    """Patches create_client in all services that use it."""
    mock = MagicMock()
    mocker.patch("services.schedule.create_client", return_value=mock)
    mocker.patch("services.user_prefs.create_client", return_value=mock)
    mocker.patch("services.rag.create_client", return_value=mock)
    return mock


def make_chunk_row(station, trains, source="weekday_schedule.pdf", row_id=1):
    """Helper to build a fake Supabase documents row in the format the DB uses.
    E.g. content = 'Info: Lawrence | 601: 7:15a | 603: 7:45a'
    """
    train_parts = " | ".join(f"{num}: {time}" for num, time in trains)
    content = f"Info: {station} | {train_parts}"
    return {
        "id": row_id,
        "content": content,
        "metadata": {"source": source},
    }
