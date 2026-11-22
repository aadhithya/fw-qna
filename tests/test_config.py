import json

from fw_qna.config import (
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_DATA_DIR,
    Settings,
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


def test_settings_round_trip_and_unknown_keys(tmp_path):
    assert Settings.load(tmp_path).context_limit == DEFAULT_CONTEXT_LIMIT
    Settings(context_limit=4000).save(tmp_path)
    assert Settings.load(tmp_path).context_limit == 4000
    (tmp_path / "settings.json").write_text(json.dumps({"context_limit": 5, "future": 1}))
    assert Settings.load(tmp_path).context_limit == 5  # unknown keys are ignored
