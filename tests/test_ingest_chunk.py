import pytest
from llama_index.core.schema import MetadataMode

from fw_qna.ingest import build_nodes
from fw_qna.ingest.chunk import MAX_CHARS, MIN_CHARS, pack
from fw_qna.ingest.clean import clean_changelog, clean_page, github_anchor

URL = "https://github.com/acme/widget"


@pytest.fixture
def nodes(release_tree):
    return build_nodes(release_tree, "v0.1.0", URL)


def by_path(nodes, path):
    return [n for n in nodes if n.metadata["path"] == path]


def test_nav_blocks_and_badges_are_removed():
    cleaned = clean_page("<!-- nav:top -->\nx\n<!-- /nav:top -->\n[![docs for](a)](b)\n# Title\n")
    assert cleaned.strip() == "# Title"


def test_commit_hashes_and_links_are_removed():
    out = clean_changelog(
        "* a thing ([abcdef1](https://x/commit/abcdef1)), closes [#1](https://x/issues/1)\n"
    )
    assert out.strip() == "* a thing"


def test_github_anchors():
    assert github_anchor("Defining an agent") == "defining-an-agent"
    assert github_anchor("0.1.0 (2026-11-20)") == "010-2026-11-20"


def test_excluded_files_are_not_indexed(nodes):
    paths = {n.metadata["path"] for n in nodes}
    assert "docs/releasing.md" not in paths
    assert "docs/book/SUMMARY.md" not in paths
    assert not any(p.startswith("docs/book/code/") for p in paths)


def test_the_layer_comes_from_the_path(nodes):
    layers = {n.metadata["path"]: n.metadata["layer"] for n in nodes}
    assert layers["docs/agents.md"] == "guide"
    assert layers["docs/book/01-start/01-install.md"] == "book"
    assert layers["docs/specs/runner.md"] == "spec"
    assert layers["CHANGELOG.md"] == "changelog"
    assert layers["examples/jobs"] == "example"


def test_the_breadcrumb_has_the_sections_own_heading(nodes):
    breadcrumbs = [n.metadata["breadcrumb"] for n in by_path(nodes, "docs/agents.md")]
    assert "Agents > Defining an agent" in breadcrumbs


def test_the_citation_url_has_the_tag_and_the_section_anchor(nodes):
    urls = {n.metadata["breadcrumb"]: n.metadata["url"] for n in by_path(nodes, "docs/agents.md")}
    assert urls["Agents > Defining an agent"] == f"{URL}/blob/v0.1.0/docs/agents.md#defining-an-agent"


def test_a_code_marker_becomes_metadata_and_leaves_the_text(nodes):
    chunk = next(n for n in by_path(nodes, "docs/book/01-start/01-install.md") if n.metadata["code_paths"])
    assert chunk.metadata["code_paths"] == ["docs/book/code/1-1/app.py"]
    assert "<!-- code:" not in chunk.text


def test_the_embedded_text_uses_the_models_document_format(nodes):
    node = next(n for n in by_path(nodes, "docs/agents.md") if "Defining" in n.metadata["breadcrumb"])
    embedded = node.get_content(MetadataMode.EMBED)
    assert embedded.startswith("title: Agents > Defining an agent (guide) | text: ")
    assert "version" not in embedded.split("| text:")[0]
    assert "https://" not in embedded.split("| text:")[0]


def test_code_blocks_are_never_split():
    code = "```python\n" + "x = 1\n" * 600 + "```"
    chunks = pack("Intro.\n\n" + code + "\n\nAfter.")
    assert any(code in c for c in chunks)
    assert all(c.count("```") % 2 == 0 for c in chunks)


def test_long_text_is_packed_near_the_limit():
    text = "\n\n".join(["A sentence that fills some space in a paragraph. " * 4] * 20)
    chunks = pack(text)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_CHARS for c in chunks)


def test_a_small_section_is_merged_into_a_neighbour(nodes):
    chunks = by_path(nodes, "docs/agents.md")
    assert all(len(n.text) >= MIN_CHARS for n in chunks)
    assert any("Tiny." in n.text for n in chunks)  # merged, not dropped


def test_neighbours_are_linked_within_a_page_only(release_tree):
    sections = "\n\n".join(f"## Part {i}\n\n" + "Some sentences about this part. " * 12 for i in range(4))
    (release_tree / "docs/long.md").write_text(f"# Long page\n\n{sections}\n")
    nodes = build_nodes(release_tree, "v0.1.0", URL)
    chunks = by_path(nodes, "docs/long.md")
    assert len(chunks) >= 3
    assert "prev_id" not in chunks[0].metadata
    assert chunks[0].metadata["next_id"] == chunks[1].node_id
    assert chunks[1].metadata["prev_id"] == chunks[0].node_id
    assert "next_id" not in chunks[-1].metadata  # the last chunk of a page does not point at the next page


def test_ids_are_deterministic_and_unique(release_tree):
    first = [n.node_id for n in build_nodes(release_tree, "v0.1.0", URL)]
    second = [n.node_id for n in build_nodes(release_tree, "v0.1.0", URL)]
    other = [n.node_id for n in build_nodes(release_tree, "v0.2.0", URL)]
    assert first == second
    assert len(set(first)) == len(first)
    assert set(first).isdisjoint(other)  # versions can sit side by side


def test_the_changelog_is_one_chunk_per_release_without_hashes(nodes):
    entries = by_path(nodes, "CHANGELOG.md")
    assert [n.metadata["release"] for n in entries] == ["0.2.0", "0.1.0"]
    assert all("commit" not in n.text and "abcdef1" not in n.text for n in entries)
    assert entries[0].metadata["url"].endswith("CHANGELOG.md#020-2026-12-01")


def test_an_example_directory_is_one_chunk_with_its_code(nodes):
    (jobs,) = by_path(nodes, "examples/jobs")
    assert "Run a job on a worker." in jobs.text and "print('run')" in jobs.text
    assert "not an example" not in jobs.text  # sample data is left out
    assert jobs.metadata["url"] == f"{URL}/tree/v0.1.0/examples/jobs"


def test_a_whole_application_is_represented_by_its_readme(nodes):
    (big,) = by_path(nodes, "examples/bigapp")
    assert "A whole application." in big.text
    assert "x = 1" not in big.text
