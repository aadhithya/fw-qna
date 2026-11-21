"""Spike: parse a release's docs with LlamaIndex's MarkdownNodeParser and look at the result.

Usage: python spikes/parse_spike.py <exported-dir> <tag> <github-repo-url>
"""

import re
import statistics
import sys
from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser

NAV = re.compile(r"<!-- nav:(top|bottom) -->.*?<!-- /nav:\1 -->\n?", re.S)
BADGE = re.compile(r"^\s*\[!\[docs for\]\([^\n]*\n?", re.M)
CODE_MARK = re.compile(r"<!-- code: (\S+) -->\n?")


def layer_of(rel: str) -> str:
    if rel.startswith("docs/book/"):
        return "book"
    if rel.startswith("docs/specs/"):
        return "spec"
    if rel.startswith("docs/"):
        return "guide"
    if rel.startswith("examples/"):
        return "example"
    return "changelog"


def slug(heading: str) -> str:  # GitHub's heading anchor
    s = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return s.replace(" ", "-")


def clean(text: str) -> str:
    return BADGE.sub("", NAV.sub("", text))


def main(root: Path, tag: str, repo: str) -> None:
    docs = []
    files = [*root.glob("docs/**/*.md"), *root.glob("examples/**/*.md")]
    for path in sorted(files):
        rel = path.relative_to(root).as_posix()
        raw = path.read_text()
        title = next((m.group(1) for m in re.finditer(r"^# (.+)$", clean(raw), re.M)), path.stem)
        docs.append(Document(text=clean(raw), metadata={
            "path": rel, "layer": layer_of(rel), "title": title, "version": tag,
        }))
    nodes = MarkdownNodeParser().get_nodes_from_documents(docs)

    for n in nodes:
        # the code marker belongs to the chunk it sits in: lift it into metadata
        marks = CODE_MARK.findall(n.text)
        if marks:
            n.metadata["code_paths"] = [f"docs/book/{m}" for m in marks]  # markers are relative to docs/book/
            missing = [c for c in n.metadata["code_paths"] if not (root / c).exists()]
            if missing:
                print("MISSING code file:", n.metadata["path"], missing)
            n.text = CODE_MARK.sub("", n.text)
        hp = n.metadata.get("header_path", "/").strip("/")
        leaf = hp.split("/")[-1] if hp else ""
        n.metadata["url"] = f"{repo}/blob/{tag}/{n.metadata['path']}" + (f"#{slug(leaf)}" if leaf else "")

    sizes = [len(n.text) for n in nodes]
    print(f"documents={len(docs)} nodes={len(nodes)}")
    print(f"chars: min={min(sizes)} median={int(statistics.median(sizes))} p90={sorted(sizes)[int(.9*len(sizes))]} max={max(sizes)}")
    print("buckets: <200:", sum(s < 200 for s in sizes), " 200-2000:", sum(200 <= s < 2000 for s in sizes),
          " 2000-6000:", sum(2000 <= s < 6000 for s in sizes), " >=6000:", sum(s >= 6000 for s in sizes))
    broken = [n for n in nodes if n.text.count("```") % 2]
    print("nodes with an unbalanced code fence:", len(broken))
    print("nodes with code_paths:", sum("code_paths" in n.metadata for n in nodes))
    print("leftover nav/badge:", sum("nav:" in n.text or "docs for" in n.text for n in nodes))
    by_layer: dict[str, int] = {}
    for n in nodes:
        by_layer[n.metadata["layer"]] = by_layer.get(n.metadata["layer"], 0) + 1
    print("by layer:", by_layer)
    print("\nlargest nodes:")
    for n in sorted(nodes, key=lambda n: -len(n.text))[:6]:
        print(f"  {len(n.text):6d}  {n.metadata['path']}  [{n.metadata.get('header_path')}]")
    print("\nsmallest nodes:")
    for n in sorted(nodes, key=lambda n: len(n.text))[:6]:
        print(f"  {len(n.text):6d}  {n.metadata['path']}  [{n.metadata.get('header_path')}]  {n.text[:60]!r}")
    for n in nodes:
        if "nav:" in n.text or "docs for" in n.text:
            print("LEFTOVER in", n.metadata["path"], repr(n.text[:120]))
    pick = next(n for n in nodes if "code_paths" in n.metadata)
    print("\nexample node metadata:", {k: v for k, v in pick.metadata.items()})
    print("--- text head ---\n" + pick.text[:500])


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
