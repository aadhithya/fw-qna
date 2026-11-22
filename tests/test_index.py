import pytest

from fw_qna.index import Index, IndexError_, version_key
from fw_qna.ingest import build_nodes

URL = "https://github.com/acme/widget"


@pytest.fixture
def nodes(release_tree):
    return build_nodes(release_tree, "v0.1.0", URL)


@pytest.fixture
def index(tmp_path, fake_embedding):
    return Index(tmp_path / "index", fake_embedding)


def test_a_new_index_is_empty(index):
    assert index.releases() == []
    assert index.latest() is None


def test_a_release_is_added_and_listed(index, nodes):
    assert index.add_release("v0.1.0", nodes) == "added"
    (info,) = index.releases()
    assert (info.version, info.chunks) == ("v0.1.0", len(nodes))
    assert (info.dimensions, info.model) == (512, "fake-embedding")
    assert index.chunks.count_rows() == len(nodes)


def test_rows_carry_what_a_citation_needs(index, nodes):
    index.add_release("v0.1.0", nodes)
    row = index.chunks.search().where("path = 'docs/book/01-start/01-install.md'").to_list()[0]
    assert row["version"] == "v0.1.0" and row["layer"] == "book"
    assert row["url"].startswith(f"{URL}/blob/v0.1.0/")
    assert any(r["code_paths"] == ["docs/book/code/1-1/app.py"] for r in index.chunks.search().to_list())


def test_ingesting_an_unchanged_release_again_embeds_nothing(index, nodes, fake_embedding):
    index.add_release("v0.1.0", nodes)
    embedded = len(fake_embedding.calls)
    assert index.add_release("v0.1.0", nodes) == "unchanged"
    assert len(fake_embedding.calls) == embedded
    assert index.chunks.count_rows() == len(nodes)


def test_force_embeds_again_without_duplicating_rows(index, nodes, fake_embedding):
    index.add_release("v0.1.0", nodes)
    embedded = len(fake_embedding.calls)
    assert index.add_release("v0.1.0", nodes, force=True) == "added"
    assert len(fake_embedding.calls) > embedded
    assert index.chunks.count_rows() == len(nodes)


def test_changed_text_replaces_the_release(index, nodes):
    index.add_release("v0.1.0", nodes)
    nodes[0].text += " A new sentence."
    assert index.add_release("v0.1.0", nodes) == "added"
    assert index.chunks.count_rows() == len(nodes)
    assert any("A new sentence." in r["text"] for r in index.chunks.search().to_list())


def test_releases_sit_side_by_side_and_drop_removes_only_one(index, release_tree):
    index.add_release("v0.1.0", build_nodes(release_tree, "v0.1.0", URL))
    index.add_release("v0.10.0", build_nodes(release_tree, "v0.10.0", URL))
    index.add_release("v0.9.0", build_nodes(release_tree, "v0.9.0", URL))
    # numeric order, not alphabetical
    assert [r.version for r in index.releases()] == ["v0.1.0", "v0.9.0", "v0.10.0"]
    assert index.latest() == "v0.10.0"
    assert index.drop("v0.9.0") is True
    assert [r.version for r in index.releases()] == ["v0.1.0", "v0.10.0"]
    assert index.chunks.search().where("version = 'v0.9.0'").to_list() == []
    assert index.chunks.search().where("version = 'v0.10.0'").to_list() != []


def test_dropping_an_unknown_release_says_so(index):
    assert index.drop("v9.9.9") is False


def test_a_version_that_is_not_a_tag_never_reaches_a_filter(index):
    with pytest.raises(ValueError):
        index.drop("v0.1.0' OR version != '")


def test_keyword_search_finds_an_exact_identifier(index, nodes):
    index.add_release("v0.1.0", nodes)
    hits = index.chunks.search("check_output", query_type="fts").limit(3).to_list()
    assert hits and "check_output" in hits[0]["text"]


def test_an_index_built_with_another_vector_size_is_refused(tmp_path, nodes, fake_embedding):
    Index(tmp_path / "index", fake_embedding).add_release("v0.1.0", nodes)
    smaller = fake_embedding.model_copy(update={"dimensions": 256})
    with pytest.raises(IndexError_, match="different vector size"):
        Index(tmp_path / "index", smaller)


def test_the_index_survives_being_reopened(tmp_path, nodes, fake_embedding):
    Index(tmp_path / "index", fake_embedding).add_release("v0.1.0", nodes)
    reopened = Index(tmp_path / "index", fake_embedding)
    assert reopened.latest() == "v0.1.0"
    assert reopened.chunks.count_rows() == len(nodes)


def test_version_key_sorts_numerically():
    assert sorted(["v0.10.0", "v0.2.0", "v1.0.0"], key=version_key) == ["v0.2.0", "v0.10.0", "v1.0.0"]
