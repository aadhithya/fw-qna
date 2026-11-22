from fw_qna import cli
from fw_qna import config as config_module


def test_init_creates_the_data_dir_and_remembers_it(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "cfg" / "config.json"
    monkeypatch.setattr(config_module, "user_config_path", lambda env=None: cfg)
    target = tmp_path / "data"
    assert cli.main(["init", str(target)]) == 0
    assert target.is_dir()
    assert config_module.resolve_data_dir(None, {}, cfg) == target
    assert str(target) in capsys.readouterr().out
