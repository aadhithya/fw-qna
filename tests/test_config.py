import pytest
import yaml

from fw_qna import cli
from fw_qna.config import (
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_DATA_DIR,
    DEFAULTS,
    HEX,
    ConfigError,
    Settings,
    default_text,
    ensure_config_file,
    resolve_data_dir,
    write_user_config,
)


def test_flag_beats_env_and_config(tmp_path):
    cfg = tmp_path / "config.json"
    write_user_config(tmp_path / "from-config", cfg)
    env = {"FW_QNA_HOME": str(tmp_path / "from-env")}
    assert resolve_data_dir(tmp_path / "flag", env, cfg) == tmp_path / "flag"


def test_env_beats_config(tmp_path):
    cfg = tmp_path / "config.json"
    write_user_config(tmp_path / "from-config", cfg)
    assert resolve_data_dir(None, {"FW_QNA_HOME": str(tmp_path / "from-env")}, cfg) == tmp_path / "from-env"


def test_config_file_then_default(tmp_path):
    cfg = tmp_path / "config.json"
    assert resolve_data_dir(None, {}, cfg) == DEFAULT_DATA_DIR  # no file yet
    write_user_config(tmp_path / "chosen", cfg)
    assert resolve_data_dir(None, {}, cfg) == tmp_path / "chosen"


def test_the_shipped_defaults_are_a_commented_valid_file():
    text = default_text()
    assert text.lstrip().startswith("#") and "context_limit:" in text
    assert DEFAULT_CONTEXT_LIMIT == 100_000
    assert set(DEFAULTS["colors"]) == {"user", "assistant", "muted", "accent", "error"}
    assert all(HEX.match(color) for color in DEFAULTS["colors"].values())


def test_without_a_file_the_defaults_are_used(tmp_path):
    settings = Settings.load(tmp_path)
    assert settings.context_limit == 100_000 and settings.colors == DEFAULTS["colors"]
    assert not (tmp_path / "config.yaml").exists()  # reading does not create it


def test_the_users_file_overrides_the_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text('context_limit: 20000\ncolors:\n  user: "#ff8800"\n')
    settings = Settings.load(tmp_path)
    assert settings.context_limit == 20_000
    assert settings.colors["user"] == "#ff8800"
    assert settings.colors["assistant"] == DEFAULTS["colors"]["assistant"]  # not set, so the default


@pytest.mark.parametrize(
    "text",
    [
        "context_limit: lots",
        "context_limit: 5",  # below the smallest sensible size
        "context_limit: true",
        "context_limit: 2.5",
        "colors: red",
        "colors:\n  user: green\n  muted: '#12345'\n  nonsense: '#123456'",
        "just a sentence",
        "",
    ],
)
def test_values_that_are_not_valid_fall_back_to_the_defaults(tmp_path, text):
    (tmp_path / "config.yaml").write_text(text)
    settings = Settings.load(tmp_path)
    assert settings.context_limit == 100_000 and settings.colors == DEFAULTS["colors"]


def test_a_file_that_is_not_yaml_is_reported_with_its_path(tmp_path):
    (tmp_path / "config.yaml").write_text("context_limit: [unclosed")
    with pytest.raises(ConfigError, match="config.yaml is not valid YAML"):
        Settings.load(tmp_path)


def test_the_commented_file_is_made_once_and_never_overwritten(tmp_path):
    path = ensure_config_file(tmp_path / "data")
    assert path.read_text() == default_text()
    path.write_text("context_limit: 7000\n")
    assert ensure_config_file(tmp_path / "data").read_text() == "context_limit: 7000\n"


def test_saving_the_limit_changes_one_line_and_keeps_the_rest(tmp_path):
    path = ensure_config_file(tmp_path)
    text = path.read_text().replace('user: "#4cc9f0"', 'user: "#ff8800"')  # the user edited a color
    path.write_text(text)
    Settings(context_limit=4000).save(tmp_path)
    saved = path.read_text()
    assert "context_limit: 4000" in saved and "context_limit: 100000" not in saved
    assert saved.count("#") == text.count("#")  # every comment and color is still there
    assert Settings.load(tmp_path).colors["user"] == "#ff8800"
    assert Settings.load(tmp_path).context_limit == 4000


def test_saving_makes_the_file_when_there_is_none_and_adds_a_missing_line(tmp_path):
    Settings(context_limit=3000).save(tmp_path / "fresh")
    assert Settings.load(tmp_path / "fresh").context_limit == 3000
    (tmp_path / "config.yaml").write_text("colors:\n  user: '#ff8800'\n")
    Settings(context_limit=9000).save(tmp_path)
    assert yaml.safe_load((tmp_path / "config.yaml").read_text())["context_limit"] == 9000


def test_the_chat_reports_an_unreadable_config_instead_of_crashing(tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise ConfigError(f"{tmp_path}/config.yaml is not valid YAML: bad")

    monkeypatch.setattr("fw_qna.chat.run_chat", broken)
    assert cli.main(["--data-dir", str(tmp_path), "chat"]) == 1
    assert "not valid YAML" in capsys.readouterr().err
