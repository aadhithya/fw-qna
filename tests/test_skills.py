import json

import pytest

from fw_qna import cli
from fw_qna.ingest import ingest_release
from fw_qna.ingest.source import SourceError, export_release
from fw_qna.skills import (
    install_skills,
    installed_skills,
    load_skills,
    remove_skills,
    skill_source,
    skills_root,
)

URL = "https://github.com/acme/widget"


def test_export_takes_the_skills_of_the_release_tag(repo, tmp_path):
    export_release(str(repo), "v0.1.0", tmp_path / "out")
    assert (tmp_path / "out/skills/featherweight/SKILL.md").is_file()
    assert (tmp_path / "out/skills/featherweight/references/recipes.md").is_file()


def test_skills_are_installed_next_to_the_index_with_where_they_came_from(release_tree, tmp_path):
    names = install_skills(release_tree, tmp_path, "v0.1.0", URL)
    assert names == ["featherweight"]  # a folder without a SKILL.md is not a skill
    root = skills_root(tmp_path, "v0.1.0")
    assert (root / "featherweight/SKILL.md").is_file() and (root / "featherweight/references/recipes.md").is_file()
    assert not (root / "not-a-skill").exists()
    assert skill_source(tmp_path, "v0.1.0") == {"repo_url": URL, "tag": "v0.1.0"}
    assert installed_skills(tmp_path, "v0.1.0") == ["featherweight"]


def test_installing_again_replaces_the_copy_and_leaves_nothing_stale(release_tree, tmp_path):
    install_skills(release_tree, tmp_path, "v0.1.0", URL)
    (skills_root(tmp_path, "v0.1.0") / "featherweight/old-file.md").write_text("from an earlier ingest")
    (release_tree / "skills/featherweight/references/recipes.md").write_text("# Recipes\n\nchanged\n")
    install_skills(release_tree, tmp_path, "v0.1.0", URL)
    root = skills_root(tmp_path, "v0.1.0") / "featherweight"
    assert not (root / "old-file.md").exists()
    assert "changed" in (root / "references/recipes.md").read_text()


def test_a_release_without_skills_installs_none_and_clears_an_old_copy(release_tree, tmp_path):
    install_skills(release_tree, tmp_path, "v0.1.0", URL)
    (tmp_path / "bare").mkdir()
    assert install_skills(tmp_path / "bare", tmp_path, "v0.1.0", URL) == []
    assert installed_skills(tmp_path, "v0.1.0") == [] and skill_source(tmp_path, "v0.1.0") is None


def test_each_release_has_its_own_skills(release_tree, tmp_path):
    install_skills(release_tree, tmp_path, "v0.1.0", URL)
    install_skills(release_tree, tmp_path, "v0.2.0", URL)
    assert remove_skills(tmp_path, "v0.1.0") is True
    assert installed_skills(tmp_path, "v0.1.0") == [] and installed_skills(tmp_path, "v0.2.0") == ["featherweight"]
    assert remove_skills(tmp_path, "v0.1.0") is False


@pytest.mark.parametrize("tag", ["main", "../evil", "v1.0.0/../../x", "v0.1.0 "])
def test_a_tag_that_is_not_a_release_never_makes_a_path(tmp_path, tag):
    with pytest.raises(SourceError):
        skills_root(tmp_path, tag)


def test_the_installed_skill_loads_as_a_featherweight_skill(release_tree, tmp_path):
    install_skills(release_tree, tmp_path, "v0.1.0", URL)
    (skill,) = load_skills(tmp_path, "v0.1.0")
    assert skill.name == "featherweight" and "Use when writing featherweight code" in skill.description
    assert "Read references/recipes.md" in skill.instructions
    assert set(skill.resources) == {"references/recipes.md"}
    assert "references/recipes.md" in skill.read()  # get_skill lists the files it can give


def test_a_skill_that_cannot_be_loaded_is_skipped_not_fatal(release_tree, tmp_path, caplog):
    install_skills(release_tree, tmp_path, "v0.1.0", URL)
    (skills_root(tmp_path, "v0.1.0") / "featherweight/SKILL.md").write_text("no frontmatter at all")
    assert load_skills(tmp_path, "v0.1.0") == []
    assert "was not loaded" in caplog.text


def test_ingest_release_installs_the_skills_when_given_a_data_directory(repo, tmp_path):
    ingest_release(str(repo), "v0.1.0", data_dir=tmp_path)
    assert installed_skills(tmp_path, "v0.1.0") == ["featherweight"]
    assert skill_source(tmp_path, "v0.1.0")["repo_url"] == "https://github.com/acme/widget"


def test_ingest_release_installs_nothing_without_one(repo, tmp_path):
    ingest_release(str(repo), "v0.1.0")
    assert not (tmp_path / "skills").exists()


@pytest.fixture
def fake_embedder(monkeypatch, fake_embedding):
    monkeypatch.setattr(cli, "make_embedder", lambda: fake_embedding)


def test_the_ingest_command_installs_the_skills_and_drop_removes_them(repo, tmp_path, fake_embedder, capsys):
    data = str(tmp_path / "data")
    assert cli.main(["--data-dir", data, "ingest", "--source", str(repo), "--ref", "v0.1.0"]) == 0
    assert "skills: featherweight" in capsys.readouterr().out
    assert (tmp_path / "data/skills/v0.1.0/featherweight/SKILL.md").is_file()
    assert json.loads((tmp_path / "data/skills/v0.1.0/source.json").read_text())["tag"] == "v0.1.0"
    # ingesting again with nothing changed still leaves the skill in place
    assert cli.main(["--data-dir", data, "ingest", "--source", str(repo), "--ref", "v0.1.0"]) == 0
    assert (tmp_path / "data/skills/v0.1.0/featherweight/SKILL.md").is_file()
    assert cli.main(["--data-dir", data, "drop", "v0.1.0"]) == 0
    assert not (tmp_path / "data/skills/v0.1.0").exists()
