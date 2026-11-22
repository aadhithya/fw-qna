import pytest

from fw_qna.ingest import ingest_release
from fw_qna.ingest.source import SourceError, check_tag, export_release, github_url


@pytest.mark.parametrize("tag", ["v0.1.0", "v10.20.30"])
def test_release_tags_are_accepted(tag):
    assert check_tag(tag) == tag


@pytest.mark.parametrize("tag", ["main", "0.1.0", "v1", "v1.2", "v1.2.3-rc1", "abc1234", "HEAD"])
def test_anything_else_is_refused(tag):
    with pytest.raises(SourceError, match="release tag"):
        check_tag(tag)


@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:acme/widget.git",
        "https://github.com/acme/widget.git",
        "https://github.com/acme/widget",
    ],
)
def test_the_citation_base_url_comes_from_the_remote(remote):
    assert github_url(remote) == "https://github.com/acme/widget"


def test_export_writes_the_release_files_and_finds_the_repo_url(repo, tmp_path):
    url = export_release(str(repo), "v0.1.0", tmp_path / "out")
    assert url == "https://github.com/acme/widget"
    assert (tmp_path / "out/docs/agents.md").is_file()
    assert (tmp_path / "out/CHANGELOG.md").is_file()
    assert (tmp_path / "out/examples/jobs/run.py").is_file()


def test_export_refuses_a_missing_tag(repo, tmp_path):
    with pytest.raises(SourceError, match="no tag v9.9.9"):
        export_release(str(repo), "v9.9.9", tmp_path / "out")


def test_export_exports_the_tag_not_the_working_tree(repo, tmp_path):
    (repo / "docs/agents.md").write_text("# Changed after the release\n")
    export_release(str(repo), "v0.1.0", tmp_path / "out")
    assert "Changed after" not in (tmp_path / "out/docs/agents.md").read_text()


def test_ingest_release_runs_the_whole_pipeline(repo):
    nodes = ingest_release(str(repo), "v0.1.0")
    assert nodes
    assert {n.metadata["version"] for n in nodes} == {"v0.1.0"}
    assert all(n.metadata["url"].startswith("https://github.com/acme/widget/") for n in nodes)


def test_ingest_release_refuses_a_branch(repo):
    with pytest.raises(SourceError, match="release tag"):
        ingest_release(str(repo), "main")
