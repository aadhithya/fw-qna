# fw-qa: project brief

Status: draft 1. Stage designs are decided one at a time (see [Design log](#design-log)).

## 1. What it is

`fw-qa` is a command-line RAG chat app over the featherweight documentation. A user opens a terminal chat, asks how something works, and gets a grounded answer with sources. When they ask for code ("how do I build a quick Redis queue for featherweight?") they get a working, idiomatic example.

## 2. Goals

1. **Answer questions** about featherweight quickly and correctly, with citations to the doc pages used.
2. **Generate example code** that follows the framework's conventions and, where feasible, is checked before it is shown.
3. **Show the framework off.** The chat agent, and any sub-agents, are featherweight agents: typed, run by `AgentRunner`, streaming, traced. The repo is itself a reference app.
4. **Know which version it is talking about.** Every indexed chunk carries the featherweight release it came from, and answers say which version they are based on.
5. **Reuse, don't rebuild.** Every pipeline stage uses an existing library. Our own code is glue and the agent.

## 3. Non-goals (v1)

- A web UI. Terminal only.
- Answering from the featherweight source code, issues or PRs. Docs only, to start (see open question Q1).
- Multi-user hosting, auth, or a managed service.
- Fine-tuning any model.
- Cross-framework answers (comparisons with LangGraph and so on) beyond what the docs themselves say.

## 4. Users

- **A developer new to featherweight** who wants to learn it by asking questions.
- **An existing user** who wants a specific snippet or the answer to "how do I do X".
- **A reader of the repo** who wants to see a real app built on featherweight.

## 5. The corpus

Source: `featherweight/docs/` (about 44 markdown files, around 500 KB), plus the runnable code under `docs/book/code/`. The layers, from the docs index: the **book** (tutorial, in order), **guides** (how to do X), **specs** (what exactly it does and why), and **examples**.

Things we have noticed that affect design:

- The book chapters reference code files in `docs/book/code/<chapter>/app.py`. Text and code belong together.
- Pages have nav comment blocks (`<!-- nav:top -->`) and badges that are noise for retrieval.
- Mermaid diagrams and many fenced code blocks. Code must never be split mid-block.
- `ALL_DOCS.md` (527 KB) is a generated concatenation of the docs. It must be excluded or every chunk is indexed twice.
- The three layers answer different questions, so a doc's layer (`book`, `guide`, `spec`, `example`) is useful metadata and can be used to weight retrieval.

## 6. Versioning

- Each ingestion is **tagged with the featherweight version** (for example `v0.1.0`) and the commit SHA.
- Ingestion reads a git ref (`--ref v0.1.0`, `--ref main`) and exports the docs from that ref, so the corpus is exactly what shipped. Today the repo has one tag, `v0.1.0`; `main` is labelled as `main@<sha>`, along with the `pyproject.toml` version.
- Several versions can sit in the index side by side. Retrieval filters by version; the default is the latest released one. The user can switch with a flag or `/version`.
- The chat shows the version in its header and in each answer's sources.

## 7. Components

```
featherweight repo --(git ref)--> [parse] -> [chunk] -> [embed] -> [index]      fw-qa ingest
                                                                       |
user <-> terminal chat <-> featherweight agent <- [retrieve (+rerank)] -+        fw-qa chat
                                 |
                          [generate answer / code (+ validate)]
```

| Stage | What it does | Candidate libraries (to be decided) |
|---|---|---|
| Parse | markdown to structured nodes; clean noise; keep code fences, tables, headings | LlamaIndex `MarkdownNodeParser`, `markdown-it-py`, `unstructured` |
| Chunk | split into retrievable units, keep heading path and attached code | LlamaIndex node parsers, `chonkie`, `langchain-text-splitters` |
| Embed | EmbeddingGemma (300M, runs locally) with its query and document prompts | `sentence-transformers` via LlamaIndex `HuggingFaceEmbedding`; or Ollama |
| Index | store vectors plus metadata, filter by version | Chroma, LanceDB, Qdrant local, or sqlite-vec; LlamaIndex vector store wrappers |
| Retrieve | version-filtered, probably hybrid (BM25 + vector), maybe reranked | LlamaIndex retrievers, `bm25s`, a cross-encoder reranker |
| Generate | answer and code from retrieved context, with citations | featherweight agent and a model it supports (Gemini, Gemma, Claude, OpenAI) |
| Chat | terminal UI, streaming, history, commands | `rich`, `prompt_toolkit`, or `textual`; featherweight streaming |

LlamaIndex is the default for ingestion, but each stage can use something else if it fits better. We will decide per stage.

## 8. Features

**Ingestion CLI** (a separate command from the chat)

- `fw-qa ingest --source ../featherweight --ref v0.1.0`
- `fw-qa versions` lists what is indexed, with doc count, chunk count and date.
- `fw-qa drop <version>`.
- Re-ingesting an unchanged version is a no-op (content hashes).
- No network call is needed to embed; the embedding model runs locally.

**Chat**

- Streaming answers in the terminal, with a short list of sources (page title, path, version).
- Multi-turn: follow-ups like "and with Postgres?" work (query rewriting from history).
- Says "the docs don't cover this" instead of guessing.
- Slash commands: `/version`, `/sources`, `/save` (write the last code example to a file), `/clear`, `/quit`.

**Code generation**

- Examples are grounded in retrieved docs and book code, not invented API.
- Generated code gets a check before it is shown: at least a syntax parse and import check; ideally a run against featherweight's fake/test models (see Q4).
- If the check fails, the agent gets the error and retries, using featherweight's own retry model.

## 9. Success criteria

- **Quality:** a small eval set of 30 to 50 questions with expected source pages (retrieval hit rate) and graded answers. Questions include "how do I build X" code requests.
- **Code:** generated examples pass the check for at least 90% of the code questions in the eval set.
- **Honesty:** questions about things not in the docs are declined, not invented.
- **Speed:** the first token in under 3 seconds on a laptop with a hosted model; ingesting the full docs in under a few minutes.
- **Demo value:** the whole app is under about 1,000 lines of our own code and reads as a clean featherweight example.

## 10. Open questions

- **Q1. Corpus scope.** Docs only, or also `examples/`, the `skills/featherweight` skill, and docstrings from `src/`? The skill and the examples are likely very good sources for code generation.
- **Q2. Which LLM** for the chat agent by default (Gemini, hosted Gemma, Claude)? Needs an API key, or should it run fully local through Ollama?
- **Q3. How embeddings run:** `sentence-transformers` in-process (pulls in torch) or Ollama (lighter Python deps, a second process).
- **Q4. How far code validation goes:** syntax and imports only, or actually executing the snippet in a sandbox with a fake model.
- **Q5. Retrieval as a tool vs. always-on.** Does the agent call a `search_docs` tool when it decides to, or is retrieval run on every turn before the model?
- **Q6. Distribution.** `uv tool install` / PyPI later; for now run from the repo.

## 11. Design log

We will go through the stages in this order, and write the decision and the reason here when each is settled.

1. Corpus and versioning (Q1, section 6)
2. Parsing
3. Chunking
4. Embedding
5. Indexing
6. Retrieval
7. Generation and the chat agent (Q2, Q4, Q5)
8. Chat UI
9. Evaluation

| Stage | Decision | Why |
|---|---|---|
| (none yet) | | |
