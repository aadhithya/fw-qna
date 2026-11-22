"""Retrieval evaluation: does the search put a page that answers the question among the first results?

A question file lists questions and the pages that would answer each (any one counts). Each question is searched
the way the chat searches (the question as the query, and the exact names as keywords, when it has any), and we
measure where the first acceptable page lands:

- **recall@k**: the share of questions with an acceptable page in the first k results.
- **MRR** (mean reciprocal rank): the average of 1 / (the rank of the first acceptable page), and 0 for a miss.

Results are ranked chunks, as the model sees them, so two chunks of one page take two ranks. This is a measurement,
not a target: nothing here is used to tune the search. It needs only the local embedder, never a chat model.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from .index import Index
from .retrieval import Retriever

DEFAULT_KS = (1, 3, 5, 10)


class EvalError(ValueError):
    """The question file is wrong, or does not fit the index."""


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    expected: list[str]
    keywords: list[str]


@dataclass(frozen=True)
class Outcome:
    question: Question
    paths: list[str]  # the path of each result, best first
    rank: int | None  # 1-based rank of the first acceptable page, or None for a miss


@dataclass(frozen=True)
class Report:
    version: str
    outcomes: list[Outcome]
    ks: tuple[int, ...] = DEFAULT_KS

    def recall_at(self, k: int) -> float:
        return sum(1 for o in self.outcomes if o.rank is not None and o.rank <= k) / len(self.outcomes)

    @property
    def mrr(self) -> float:
        return sum(1 / o.rank for o in self.outcomes if o.rank) / len(self.outcomes)

    @property
    def misses(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.rank is None or o.rank > max(self.ks)]


def load_questions(path: Path) -> tuple[str, list[Question]]:
    """Read a question file. Return its version and its questions."""
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise EvalError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list) or not data.get("version"):
        raise EvalError(f"{path} needs a `version` and a list of `questions`")
    questions, seen = [], set()
    for item in data["questions"]:
        if not isinstance(item, dict):
            raise EvalError(f"every question must be a mapping, not {item!r}")
        name = item.get("id")
        if not name or not item.get("question"):
            raise EvalError(f"every question needs an `id` and a `question`: {item!r}")
        if name in seen:
            raise EvalError(f"the question id {name!r} is used twice")
        seen.add(name)
        expected = item.get("expected")
        if not isinstance(expected, list) or not expected or not all(isinstance(p, str) for p in expected):
            raise EvalError(f"question {name!r} needs a non-empty list of `expected` pages")
        questions.append(Question(name, item["question"], list(expected), list(item.get("keywords") or [])))
    if not questions:
        raise EvalError(f"{path} has no questions")
    return str(data["version"]), questions


def indexed_paths(index: Index, version: str) -> set[str]:
    rows = index.chunks.search().where(f"version = '{version}'").select(["path"]).limit(1_000_000).to_list()
    return {row["path"] for row in rows}


def evaluate(retriever: Retriever, version: str, questions: list[Question], ks: tuple[int, ...] = DEFAULT_KS) -> Report:
    """Run every question. A page named in the file that is not in the index is an error, not a miss."""
    known = indexed_paths(retriever.index, version)
    unknown = sorted({p for q in questions for p in q.expected} - known)
    if unknown:
        raise EvalError(f"expected pages that are not in the index for {version}: {', '.join(unknown)}")
    outcomes = []
    for q in questions:
        hits = retriever.search(q.question, keywords=q.keywords or None, version=version, top_k=max(ks))
        paths = [hit.path for hit in hits]
        rank = next((i for i, path in enumerate(paths, 1) if path in q.expected), None)
        outcomes.append(Outcome(q, paths, rank))
    return Report(version, outcomes, ks)


def format_report(report: Report) -> str:
    """The report as text: one line per question, then the numbers."""
    lines = [f"Retrieval eval on {report.version}: {len(report.outcomes)} questions", ""]
    for o in report.outcomes:
        rank = f"{o.rank:>2}" if o.rank else " -"
        top = o.paths[0] if o.paths else "(no results)"
        lines.append(f"  {rank}  {o.question.id:<18} {o.question.question[:58]:<58}  top: {top}")
    lines.append("")
    for k in report.ks:
        found = round(report.recall_at(k) * len(report.outcomes))
        lines.append(f"  recall@{k:<2} {report.recall_at(k):.2f}   ({found} of {len(report.outcomes)})")
    lines.append(f"  MRR       {report.mrr:.3f}")
    if report.misses:
        lines += ["", f"  not in the top {max(report.ks)}:"]
        lines += [f"    {o.question.id}: wanted {', '.join(o.question.expected)}" for o in report.misses]
    lines += ["", "  A measurement, not a target: the pipeline is not tuned against it."]
    return "\n".join(lines)
