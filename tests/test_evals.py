from pathlib import Path

import pytest

from fw_qna import cli
from fw_qna.evals import EvalError, Outcome, Question, Report, evaluate, format_report, load_questions
from fw_qna.index import Index
from fw_qna.ingest import build_nodes
from fw_qna.retrieval import Retriever

URL = "https://github.com/acme/widget"
QUESTIONS = Path(__file__).parent.parent / "evals" / "retrieval.yaml"


def question(name="q", expected=("a.md",)):
    return Question(name, "a question?", list(expected), [])


def report(*ranks):
    return Report("v0.1.0", [Outcome(question(f"q{i}"), [], rank) for i, rank in enumerate(ranks)])


def test_recall_at_k_is_the_share_of_questions_found_in_the_first_k():
    r = report(1, 3, 5, None)
    assert [r.recall_at(k) for k in (1, 3, 5, 10)] == [0.25, 0.5, 0.75, 0.75]


def test_mrr_is_the_mean_of_one_over_the_rank_and_zero_for_a_miss():
    assert report(1, 2, None, 4).mrr == pytest.approx((1 + 0.5 + 0 + 0.25) / 4)
    assert report(1, 1).mrr == 1.0
    assert report(None, None).mrr == 0.0


def test_misses_are_the_questions_not_found_in_the_largest_k():
    assert [o.question.id for o in report(1, None, 20).misses] == ["q1", "q2"]


def test_the_report_shows_each_question_and_the_numbers():
    text = format_report(report(1, None))
    assert "recall@1  0.50   (1 of 2)" in text and "MRR       0.500" in text
    assert "not in the top 10:" in text and "q1: wanted a.md" in text
    assert "not tuned" in text


def write(tmp_path, text):
    path = tmp_path / "q.yaml"
    path.write_text(text)
    return path


def test_a_question_file_is_read(tmp_path):
    version, questions = load_questions(
        write(tmp_path, "version: v0.1.0\nquestions:\n  - {id: a, question: Why, expected: [x.md], keywords: [Foo]}\n")
    )
    assert version == "v0.1.0" and questions == [Question("a", "Why", ["x.md"], ["Foo"])]


@pytest.mark.parametrize(
    "text, message",
    [
        ("questions: []", "needs a `version`"),
        ("version: v0.1.0\nquestions: []", "no questions"),
        ("version: v0.1.0\nquestions:\n  - {id: a, question: Q}", "non-empty list of `expected`"),
        ("version: v0.1.0\nquestions:\n  - {id: a, question: Q, expected: []}", "non-empty list of `expected`"),
        ("version: v0.1.0\nquestions:\n  - {question: Q, expected: [x]}", "needs an `id`"),
        (
            "version: v0.1.0\nquestions:\n  - {id: a, question: Q, expected: [x]}\n"
            "  - {id: a, question: R, expected: [y]}",
            "used twice",
        ),
        ("version: [unclosed", "cannot read"),
    ],
)
def test_a_wrong_question_file_says_what_is_wrong(tmp_path, text, message):
    with pytest.raises(EvalError, match=message):
        load_questions(write(tmp_path, text))


def test_the_real_question_file_is_well_formed():
    version, questions = load_questions(QUESTIONS)
    assert version == "v0.1.0" and 15 <= len(questions) <= 25
    for q in questions:
        assert q.question.endswith("?") and q.expected
        assert all(p.startswith(("docs/", "examples/")) or p == "CHANGELOG.md" for p in q.expected), q.id
        assert all(p.endswith(".md") or p.startswith("examples/") for p in q.expected), q.id


@pytest.fixture
def retriever(tmp_path, release_tree, words_embedding):
    (release_tree / "docs/jobs.md").write_text("# Jobs\n\nThe JobWorker takes a job from the queue and runs it. " * 6)
    (release_tree / "docs/validation.md").write_text("# Validation\n\nUse check_output to reject a bad answer. " * 6)
    index = Index(tmp_path / "index", words_embedding)
    index.add_release("v0.1.0", build_nodes(release_tree, "v0.1.0", URL))
    return Retriever(index)


def test_each_question_is_ranked_by_its_first_acceptable_page(retriever):
    questions = [
        Question("jobs", "who takes a job from the queue and runs it", ["docs/jobs.md"], []),
        Question("check", "reject a bad answer", ["docs/validation.md"], ["check_output"]),
        Question("either", "job queue worker", ["docs/specs/runner.md", "docs/jobs.md"], ["JobWorker"]),
        Question("miss", "job queue worker", ["docs/specs/runner.md"], []),
    ]
    outcomes = {o.question.id: o for o in evaluate(retriever, "v0.1.0", questions).outcomes}
    assert outcomes["jobs"].rank == 1 and outcomes["jobs"].paths[0] == "docs/jobs.md"
    assert outcomes["check"].rank == 1  # the exact name is passed as a keyword, as the chat does
    assert outcomes["either"].rank is not None  # any one acceptable page counts
    assert outcomes["miss"].rank is None or outcomes["miss"].rank > 1


def test_a_page_that_is_not_in_the_index_is_an_error_not_a_miss(retriever):
    with pytest.raises(EvalError, match="not in the index for v0.1.0: docs/typo.md"):
        evaluate(retriever, "v0.1.0", [question(expected=["docs/typo.md"])])


def test_the_eval_command_prints_a_report(tmp_path, retriever, words_embedding, monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_embedder", lambda: words_embedding)
    path = write(
        tmp_path,
        "version: v0.1.0\nquestions:\n"
        "  - {id: jobs, question: who takes a job from the queue, expected: [docs/jobs.md]}\n",
    )
    assert cli.main(["--data-dir", str(tmp_path), "eval", "--questions", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Retrieval eval on v0.1.0: 1 questions" in out and "MRR" in out and "recall@5" in out


def test_the_eval_command_reports_a_typo_in_the_file(tmp_path, retriever, words_embedding, monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_embedder", lambda: words_embedding)
    path = write(tmp_path, "version: v0.1.0\nquestions:\n  - {id: a, question: Q?, expected: [docs/typo.md]}\n")
    assert cli.main(["--data-dir", str(tmp_path), "eval", "--questions", str(path)]) == 1
    assert "docs/typo.md" in capsys.readouterr().err
