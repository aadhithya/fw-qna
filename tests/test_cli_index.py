import pytest

from fw_qna import cli


@pytest.fixture(autouse=True)
def fake_ollama(monkeypatch, fake_embedding):
    monkeypatch.setattr(cli, "make_embedder", lambda: fake_embedding)


def run(tmp_path, *args):
    return cli.main(["--data-dir", str(tmp_path / "data"), *args])


def test_ingest_then_list_then_drop(repo, tmp_path, capsys):
    assert run(tmp_path, "ingest", "--source", str(repo), "--ref", "v0.1.0") == 0
    assert "indexed" in capsys.readouterr().out
    assert run(tmp_path, "versions") == 0
    assert "v0.1.0" in capsys.readouterr().out
    assert run(tmp_path, "drop", "v0.1.0") == 0
    assert run(tmp_path, "versions") == 0
    assert "Nothing is indexed yet" in capsys.readouterr().out


def test_ingesting_twice_says_nothing_changed(repo, tmp_path, capsys):
    run(tmp_path, "ingest", "--source", str(repo), "--ref", "v0.1.0")
    capsys.readouterr()
    assert run(tmp_path, "ingest", "--source", str(repo), "--ref", "v0.1.0") == 0
    assert "nothing changed" in capsys.readouterr().out


def test_a_branch_is_refused_with_a_clear_message(repo, tmp_path, capsys):
    assert run(tmp_path, "ingest", "--source", str(repo), "--ref", "main") == 1
    assert "release tag" in capsys.readouterr().err


def test_dropping_something_not_indexed_fails(tmp_path, capsys):
    assert run(tmp_path, "drop", "v0.1.0") == 1
    assert "not indexed" in capsys.readouterr().out
