import json

import pytest

from fw_qna.index import Index
from fw_qna.ingest import build_nodes
from fw_qna.retrieval import Retriever, SearchError, keyword_query
from fw_qna.search_tool import DocSearch, SearchArgs

URL = "https://github.com/acme/widget"


def page(title, body):
    return f"# {title}\n\n{body}\n"


@pytest.fixture
def tree(release_tree):
    """The shared tree, plus pages with distinct topics and four example directories about queues."""
    docs = release_tree / "docs"
    (docs / "jobs.md").write_text(
        page("Jobs", "A job runs agents in a pipeline. The JobWorker takes a job from the queue. " * 4)
    )
    (docs / "validation.md").write_text(
        page("Validation", "Use check_output to reject an answer the schema cannot express. " * 5)
    )
    for i in range(4):
        d = release_tree / f"examples/queue{i}"
        d.mkdir(parents=True)
        (d / "README.md").write_text(f"# Queue {i}\n\nA worker takes jobs from a queue and runs them.\n")
        (d / "run.py").write_text("print('queue worker')\n")
    return release_tree


@pytest.fixture
def retriever(tmp_path, tree, words_embedding):
    index = Index(tmp_path / "index", words_embedding)
    index.add_release("v0.1.0", build_nodes(tree, "v0.1.0", URL))
    index.add_release("v0.2.0", build_nodes(tree, "v0.2.0", URL))
    return Retriever(index)


def test_keyword_query_drops_syntax_characters():
    assert keyword_query('check_output() AND "x:y" *') == "check_output AND x y"
    assert keyword_query("???") == ""


def test_the_latest_release_is_searched_by_default(retriever):
    hits = retriever.search("how does a job run on a worker")
    assert hits and {h.version for h in hits} == {"v0.2.0"}


def test_a_named_release_is_searched_instead(retriever):
    assert {h.version for h in retriever.search("job worker queue", version="v0.1.0")} == {"v0.1.0"}


def test_an_unindexed_release_is_explained(retriever):
    with pytest.raises(SearchError, match=r"v0\.9\.0 is not indexed. Indexed releases: v0\.1\.0, v0\.2\.0"):
        retriever.search("job", version="v0.9.0")


def test_a_version_that_is_not_a_tag_is_refused(retriever):
    with pytest.raises(ValueError):
        retriever.search("job", version="v0.1.0' OR version != '")


def test_an_empty_index_is_explained(tmp_path, words_embedding):
    with pytest.raises(SearchError, match="Nothing is indexed"):
        Retriever(Index(tmp_path / "empty", words_embedding)).search("job")


def test_the_layer_filter_limits_the_results(retriever):
    hits = retriever.search("job worker queue", layer="guide", top_k=10)
    assert hits and {h.layer for h in hits} == {"guide"}


def test_an_unknown_layer_is_refused(retriever):
    with pytest.raises(SearchError, match="layer must be one of"):
        retriever.search("job", layer="blog")


def test_top_k_limits_the_results(retriever):
    assert len(retriever.search("job worker", top_k=2)) == 2


def test_keywords_find_an_exact_name_a_sentence_would_miss(retriever):
    hits = retriever.search("how do I make sure the answer is acceptable", keywords=["check_output"], top_k=3)
    assert "check_output" in hits[0].text


def test_a_search_returns_at_most_two_examples(retriever):
    hits = retriever.search("worker takes jobs from a queue and runs them", top_k=8)
    assert sum(h.layer == "example" for h in hits) == 2


def test_asking_for_the_example_layer_is_not_capped(retriever):
    hits = retriever.search("worker takes jobs from a queue", layer="example", top_k=4)
    assert sum(h.layer == "example" for h in hits) == 4


AWKWARD = ["check_output()", '"quoted" words', "a:b", "AND OR NOT *", "???", "(((", "\\"]


@pytest.mark.parametrize("query", AWKWARD)
def test_awkward_queries_do_not_crash(retriever, query):
    assert isinstance(retriever.search(query), list)


async def test_the_async_search_gives_the_same_hits(retriever):
    sync = [h.id for h in retriever.search("job worker queue")]
    assert [h.id for h in await retriever.asearch("job worker queue")] == sync


@pytest.fixture
def docsearch(retriever):
    return DocSearch(retriever)


async def test_the_tool_returns_numbered_results_as_json(docsearch):
    result = json.loads(await docsearch.search("job worker queue", top_k=3))
    assert result["version"] == "v0.2.0"
    assert [r["ref"] for r in result["results"]] == [1, 2, 3]
    first = result["results"][0]
    assert first["url"].startswith(f"{URL}/") and "/v0.2.0/" in first["url"]
    assert {"title", "layer", "version", "code_files", "text"} <= first.keys()


async def test_a_chunk_keeps_its_number_for_the_whole_conversation(docsearch):
    first = json.loads(await docsearch.search("job worker queue", top_k=3))
    again = json.loads(await docsearch.search("job worker queue", top_k=3))
    assert [r["ref"] for r in again["results"]] == [r["ref"] for r in first["results"]]
    other = json.loads(await docsearch.search("check_output", keywords=["check_output"], top_k=2))
    assert min(r["ref"] for r in other["results"]) >= 1
    refs = {r["ref"] for r in first["results"]} | {r["ref"] for r in other["results"]}
    assert set(docsearch.citations) == refs  # the interface can look every one up


async def test_citations_carry_the_title_and_link(docsearch):
    result = json.loads(await docsearch.search("job worker queue", top_k=1))
    citation = docsearch.citations[result["results"][0]["ref"]]
    assert citation.url == result["results"][0]["url"]
    assert citation.breadcrumb == result["results"][0]["title"]


async def test_the_tool_reports_an_error_as_text_not_an_exception(docsearch):
    assert "not indexed" in json.loads(await docsearch.search("job", version="v0.9.0"))["error"]


async def test_the_tool_says_when_nothing_matched(tmp_path, tree, words_embedding):
    index = Index(tmp_path / "i", words_embedding)
    index.add_release("v0.1.0", build_nodes(tree, "v0.1.0", URL))
    result = json.loads(await DocSearch(Retriever(index)).search("job", layer="changelog", keywords=["zzzz"]))
    assert "results" in result  # a list, possibly empty, never an exception


async def test_the_tool_can_be_called_the_way_an_agent_calls_it(docsearch):
    tool = docsearch.tool()
    assert tool.name == "search_docs"
    assert "EVERY question about featherweight" in tool.description
    out = await tool.ainvoke({"query": "job worker", "keywords": ["JobWorker"], "top_k": 2})
    assert len(json.loads(out)["results"]) == 2


def test_the_tools_arguments_are_checked():
    with pytest.raises(ValueError):
        SearchArgs(query="x", layer="blog")
    with pytest.raises(ValueError):
        SearchArgs(query="x", top_k=0)
