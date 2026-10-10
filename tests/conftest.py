import pytest


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Never touch the real sidequest.db / quest_library.db / user_history.db from tests."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("LIBRARY_PATH", str(tmp_path / "quest_library.db"))
    monkeypatch.setenv("HISTORY_PATH", str(tmp_path / "user_history.db"))
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
