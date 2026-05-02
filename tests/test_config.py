from hermes_polymarket.config import PROJECT_ROOT, load_settings


def test_default_mode_is_paper_and_live_disabled():
    settings = load_settings()
    assert settings.mode == "paper"
    assert settings.allow_live_trading is False
    assert settings.max_order_usd == 10.0


def test_database_path_env_override_relative(monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", "data/parallel/test.sqlite3")

    settings = load_settings()

    assert settings.database_path == PROJECT_ROOT / "data/parallel/test.sqlite3"


def test_database_path_env_override_absolute(monkeypatch, tmp_path):
    db_path = tmp_path / "isolated.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    settings = load_settings()

    assert settings.database_path == db_path


def test_hermes_database_path_env_override(monkeypatch, tmp_path):
    db_path = tmp_path / "hermes.sqlite3"
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(db_path))

    settings = load_settings()

    assert settings.database_path == db_path
