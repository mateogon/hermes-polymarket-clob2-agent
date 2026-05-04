from hermes_polymarket.config import PROJECT_ROOT, load_settings


def test_default_mode_is_paper_and_live_disabled():
    settings = load_settings()
    assert settings.mode == "paper"
    assert settings.environment == "default"
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


def test_hermes_database_path_takes_precedence(monkeypatch, tmp_path):
    database_path = tmp_path / "database.sqlite3"
    hermes_path = tmp_path / "hermes.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(hermes_path))

    settings = load_settings()

    assert settings.database_path == hermes_path


def test_research_environment_uses_research_paths(monkeypatch):
    monkeypatch.setenv("HERMES_ENV", "research")

    settings = load_settings()

    assert settings.environment == "research"
    assert settings.mode == "research"
    assert settings.database_path == PROJECT_ROOT / "data/research/research.sqlite3"
    assert settings.artifact_dir == PROJECT_ROOT / "artifacts/research"
    assert settings.allow_live_trading is False
    assert settings.requires_pre_live_audit is False


def test_trading_real_environment_forces_live_disabled(monkeypatch):
    monkeypatch.setenv("HERMES_ENV", "trading_real")
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "true")

    settings = load_settings()

    assert settings.environment == "trading_real"
    assert settings.mode == "trading_real"
    assert settings.database_path == PROJECT_ROOT / "data/trading_real/trading_real.sqlite3"
    assert settings.artifact_dir == PROJECT_ROOT / "artifacts/trading_real"
    assert settings.allow_live_trading is False
    assert settings.requires_pre_live_audit is True


def test_artifact_dir_env_override_relative(monkeypatch):
    monkeypatch.setenv("HERMES_ARTIFACTS_DIR", "artifacts/custom")

    settings = load_settings()

    assert settings.artifact_dir == PROJECT_ROOT / "artifacts/custom"
