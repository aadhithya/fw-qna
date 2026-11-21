"""Spike: chunk a release's docs, changelog and examples under the agreed rules.

Usage: python spikes/chunk_spike.py <exported-dir> <tag> <github-repo-url>
"""

import re
import statistics
import sys
import uuid
from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.core.schema import MetadataMode, TextNode

from parse_spike import CODE_MARK, clean, layer_of, slug

MAX, MIN, DIR_MAX = 1500, 200, 12000
EXCLUDE = ("docs/releasing.md", "docs/development.md", "docs/book/SUMMARY.md", "docs/book/STYLE.md", "docs/book/code/")
HASHES = re.compile(r" \(\[[0-9a-f]{7}\]\([^)]*\)\)(, closes \[#\d+\]\([^)]*\))?")
EMBED_KEYS = {"layer", "title", "breadcrumb"}


def blocks(text: str) -> list[str]:
    """Split at blank lines, but never inside a fenced code block."""
    out, cur, fenced = [], [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        if not line.strip() and not fenced:
            if cur:
                out.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return out


def pack(text: str) -> list[str]:
    """Greedy paragraph packing up to MAX. A single block over MAX (a code fence) stays whole."""
    if len(text) <= MAX:
        return [text]
    chunks, cur = [], ""
    parts = []
    for b in blocks(text):
        if len(b) > MAX and not b.startswith("```"):
            parts += b.split("\n")  # a long table or list: split by lines
        else:
            parts.append(b)
    for b in parts:
        if cur and len(cur) + len(b) + 2 > MAX:
            chunks.append(cur)
            cur = b
        else:
            cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        chunks.append(cur)
    return chunks


def merge_small(items: list[dict]) -> list[dict]:
    """Merge chunks under MIN into the next chunk of the same document (or the previous one at the end)."""
    out: list[dict] = []
    carry = None
    for it in items:
        if carry:
            if carry["path"] == it["path"]:
                it = {**it, "text": carry["text"] + "\n\n" + it["text"]}
            else:
                out[-1]["text"] += "\n\n" + carry["text"] if out and out[-1]["path"] == carry["path"] else ""
            carry = None
        if len(it["text"]) < MIN:
            carry = it
        else:
            out.append(it)
    if carry:
        if out and out[-1]["path"] == carry["path"]:
            out[-1]["text"] += "\n\n" + carry["text"]
        else:
            out.append(carry)
    return out


def markdown_items(root: Path, tag: str) -> list[dict]:
    docs = []
    for path in sorted(root.glob("docs/**/*.md")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(EXCLUDE):
            continue
        text = clean(path.read_text())
        title = next((m.group(1) for m in re.finditer(r"^# (.+)$", text, re.M)), path.stem)
        docs.append(Document(text=text, metadata={"path": rel, "title": title}))
    items = []
    for n in MarkdownNodeParser().get_nodes_from_documents(docs):
        hp = [h for h in n.metadata.get("header_path", "/").strip("/").split("/") if h]
        marks = CODE_MARK.findall(n.text)
        own = re.match(r"#{1,6} (.+)", n.text.lstrip())
        if own and own.group(1) not in hp:
            hp.append(own.group(1))
        text = CODE_MARK.sub("", n.text).strip()
        for piece in pack(text):
            items.append({
                "text": piece, "path": n.metadata["path"], "title": n.metadata["title"],
                "layer": layer_of(n.metadata["path"]), "headings": hp,
                "code_paths": [f"docs/book/{m}" for m in marks],
            })
    return merge_small(items)


def changelog_items(root: Path) -> list[dict]:
    text = re.sub(r"\n{3,}", "\n\n", HASHES.sub("", (root / "CHANGELOG.md").read_text()))
    entries = re.split(r"(?m)^(?=## \d)", text)
    return [{"text": e.strip(), "path": "CHANGELOG.md", "title": "Changelog", "layer": "changelog",
             "headings": [e.splitlines()[0].lstrip("# ")], "code_paths": [], "unit": True}
            for e in entries if re.match(r"## \d", e)]


def example_items(root: Path) -> list[dict]:
    items = []
    for d in sorted(p for p in (root / "examples").iterdir() if p.is_dir()):
        parts = []
        readme = d / "README.md"
        files = ([readme] if readme.exists() else []) + sorted(
            f for f in d.rglob("*") if f.suffix in (".py", ".md") and f != readme and "samples" not in f.parts)
        for f in files:
            body = f.read_text().strip()
            parts.append(body if f == readme else f"### {f.relative_to(d).as_posix()}\n\n```python\n{body}\n```"
                         if f.suffix == ".py" else f"### {f.relative_to(d).as_posix()}\n\n{body}")
        body = "\n\n".join(parts)
        if len(body) > DIR_MAX and readme.exists():  # a whole app, not an example: the README is the unit
            body = readme.read_text().strip() + f"\n\n(The full source, {len(files) - 1} more files, is in the directory.)"
        items.append({"text": body, "path": f"examples/{d.name}", "title": f"Example: {d.name}",
                      "layer": "example", "headings": [], "code_paths": [], "unit": True, "dir": True})
    return items


def to_nodes(items: list[dict], tag: str, repo: str) -> list[TextNode]:
    nodes = []
    for it in items:
        leaf = it["headings"][-1] if it["headings"] else ""
        kind = "tree" if it.get("dir") else "blob"
        url = f"{repo}/{kind}/{tag}/{it['path']}" + (f"#{slug(leaf)}" if leaf and leaf != it["title"] else "")
        n = TextNode(id_=str(uuid.uuid4()), text=it["text"], metadata={
            "version": tag, "layer": it["layer"], "title": it["title"],
            "breadcrumb": " > ".join([it["title"], *[h for h in it["headings"] if h != it["title"]]]),
            "path": it["path"], "url": url, "code_paths": it["code_paths"],
        })
        n.excluded_embed_metadata_keys = [k for k in n.metadata if k not in EMBED_KEYS]
        n.excluded_llm_metadata_keys = ["version", "code_paths"]
        nodes.append(n)
    # prev/next within the same document
    for a, b in zip(nodes, nodes[1:]):
        if a.metadata["path"] == b.metadata["path"]:
            a.metadata["next_id"], b.metadata["prev_id"] = b.node_id, a.node_id
            a.excluded_embed_metadata_keys += ["next_id"]
            b.excluded_embed_metadata_keys += ["prev_id"]
    return nodes


def main(root: Path, tag: str, repo: str) -> None:
    nodes = to_nodes([*markdown_items(root, tag), *changelog_items(root), *example_items(root)], tag, repo)
    sizes = [len(n.text) for n in nodes]
    print(f"chunks={len(nodes)}")
    print(f"chars: min={min(sizes)} median={int(statistics.median(sizes))} p90={sorted(sizes)[int(.9*len(sizes))]} max={max(sizes)}")
    print("<200:", sum(s < MIN for s in sizes), " 200-1500:", sum(MIN <= s <= MAX for s in sizes),
          " 1500-3000:", sum(MAX < s <= 3000 for s in sizes), " >3000:", sum(s > 3000 for s in sizes))
    by: dict[str, list[int]] = {}
    for n in nodes:
        by.setdefault(n.metadata["layer"], []).append(len(n.text))
    for k, v in by.items():
        print(f"  {k:10s} n={len(v):4d} median={int(statistics.median(v)):5d} max={max(v)}")
    print("broken fences:", sum(n.text.count("```") % 2 for n in nodes))
    print("\nover 3000 chars:")
    for n in sorted(nodes, key=lambda n: -len(n.text)):
        if len(n.text) > 3000:
            print(f"  {len(n.text):6d} {n.metadata['layer']:9s} {n.metadata['path']}  [{n.metadata['breadcrumb']}]")
    print("\nstill under 200 chars:")
    for n in nodes:
        if len(n.text) < MIN:
            print(f"  {len(n.text):4d} {n.metadata['path']} {n.text[:70]!r}")
    pick = next(n for n in nodes if n.metadata["path"] == "docs/agents.md" and "prev_id" in n.metadata)
    print("\n=== embedded text of one chunk ===\n" + pick.get_content(MetadataMode.EMBED)[:700])
    print("\n=== metadata ===", {k: v for k, v in pick.metadata.items() if k not in ("prev_id", "next_id")})
    cl = next(n for n in nodes if n.metadata["layer"] == "changelog")
    print("\nchangelog sample:", cl.metadata["url"], len(cl.text), repr(cl.text[:200]))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
