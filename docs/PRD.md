# fw-qna: project brief

Status: version 1.0.0. The stages were designed one at a time; the decisions and the reasons are in the [design log](#design-log). The README describes the app as it is.

## 1. What it is

`fw-qna` is a command-line RAG chat app over the featherweight documentation. A user opens a terminal chat, asks how something works, and gets a grounded answer with sources. When they ask for code ("how do I build a quick Redis queue for featherweight?") they get a working, idiomatic example.

## 2. Goals

1. **Answer questions** about featherweight quickly and correctly, with citations to the doc pages used.
2. **Generate example code** that follows the framework's conventions, grounded in the docs.
3. **Show the framework off.** The chat agent, and any sub-agents, are featherweight agents: typed, run by `AgentRunner`, streaming, traced. The repo is itself a reference app.
4. **Know which version it is talking about.** Every indexed chunk carries the featherweight release it came from, and answers say which version they are based on.
5. **Reuse, don't rebuild.** Every pipeline stage uses an existing library. Our own code is glue and the agent.

## 3. Non-goals (v1)

- A web UI. Terminal only.
- Answering from the featherweight source code, its skill, issues or PRs. Docs, changelog and examples only.
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
- Ingestion reads a release tag (`--ref v0.1.0`) and exports the docs from that tag, so the corpus is exactly what shipped. Only tags of the form `vX.Y.Z` are accepted. Branches and bare commits are rejected, so there is no `main` index. Today the repo has one tag, `v0.1.0`.
- Several versions can sit in the index side by side. Retrieval filters by version; the default is the latest released one. The user can switch with a flag or `/version`.
- The chat shows the version in its header and in each answer's sources.

## 7. Components

```
featherweight repo --(git ref)--> [parse] -> [chunk] -> [embed] -> [index]      fw-qna ingest
                                                                       |
user <-> terminal chat <-> featherweight agent <- [retrieve (+rerank)] -+        fw-qna chat
                                 |
                          [generate answer / code (+ validate)]
```

| Stage | What it does | Candidate libraries (to be decided) |
|---|---|---|
| Parse | markdown to structured nodes; clean noise; keep code fences, tables, headings | LlamaIndex `MarkdownNodeParser`, `markdown-it-py`, `unstructured` |
| Chunk | split into retrievable units, keep heading path and attached code | LlamaIndex node parsers, `chonkie`, `langchain-text-splitters` |
| Embed | EmbeddingGemma 2 (runs locally) with its query and document prompts | Ollama over HTTP; a thin LlamaIndex embedding class (LlamaIndex has an Ollama embedding integration) |
| Index | store vectors plus metadata, filter by version | Chroma, LanceDB, Qdrant local, or sqlite-vec; LlamaIndex vector store wrappers |
| Retrieve | version-filtered, probably hybrid (BM25 + vector), maybe reranked | LlamaIndex retrievers, `bm25s`, a cross-encoder reranker |
| Generate | answer and code from retrieved context, with citations | featherweight agent and a model it supports (Gemini, Gemma, Claude, OpenAI) |
| Chat | terminal UI, streaming, history, commands | `rich`, `prompt_toolkit`, or `textual`; featherweight streaming |

LlamaIndex is the default for ingestion, but each stage can use something else if it fits better. We will decide per stage.

## 8. Features

**Ingestion CLI** (a separate command from the chat)

- `fw-qna ingest --source ../featherweight --ref v0.1.0` (release tags only)
- `fw-qna versions` lists what is indexed, with doc count, chunk count and date.
- `fw-qna drop <version>`.
- Re-ingesting an unchanged version is a no-op (content hashes).
- No network call is needed to embed; the embedding model runs locally.

**Chat**

- Streaming answers in the terminal, with a short list of sources (page title, path, version).
- Multi-turn: follow-ups like "and with Postgres?" work (query rewriting from history).
- Says "the docs don't cover this" instead of guessing (a system-prompt rule). The sources list comes from the `search_docs` results in the run, not from what the model claims.
- Slash commands: `/version`, `/sources`, `/save` (write the last code example to a file), `/clear`, `/quit`.

**Code generation**

- Examples are grounded in retrieved docs and book code, not invented API. They are minimal, with comments that explain the choices made in the code.
- There is no code checking. The model's code is shown as it is generated.
- Diagrams are drawn as simple markdown or text diagrams, not Mermaid.

## 9. Success criteria and evals

The app is judged by use and as a demo:

- Answers cite their sources, and the links open the right page at the right tag.
- Questions the docs do not cover are declined, not invented.
- Generated code follows the framework's conventions.
- The first token arrives in under 3 seconds on a laptop with a hosted model, and ingesting the docs takes a few minutes.
- The whole app is small (about 1,000 lines of our own code) and reads as a clean featherweight example.

**Evals are a final-stage demonstration.** They show that evaluation is available, and are not used to tune the pipeline:

- **Retrieval evals:** a small question set with the expected source pages, scored with recall@k and MRR.
- **Generation evals:** a separate topic, designed at the end.
- We report the numbers. We do not change chunking, embeddings or prompts to improve them.

## 10. Open questions

- ~~**Q1. Corpus scope.**~~ Decided, see the design log. Original question: Docs only, or also `examples/`, the `skills/featherweight` skill, and docstrings from `src/`? The skill and the examples are likely very good sources for code generation.
- ~~**Q2. Which LLM**~~ Decided (Haiku 5.5). Original question: for the chat agent by default (Gemini, hosted Gemma, Claude)? Needs an API key, or should it run fully local through Ollama?
- ~~**Q3. How embeddings run:**~~ Decided (Ollama over HTTP, no PyTorch). Original question: `sentence-transformers` in-process (pulls in torch) or Ollama (lighter Python deps, a second process).
- **Q4. How far code validation goes:** syntax and imports only, or actually executing the snippet in a sandbox with a fake model.
- ~~**Q5. Retrieval as a tool vs. always-on.**~~ Decided (tool, not enforced). Original question: Does the agent call a `search_docs` tool when it decides to, or is retrieval run on every turn before the model?
- ~~**Q7. How llama.cpp is delivered.**~~ Decided: Ollama, over HTTP, in Docker (see the design log). Findings that led here: `llama-cpp-python` is source-only on PyPI (needs a compiler), its prebuilt Metal wheel was corrupt when tried, and MLX needs an unreleased `mlx-vlm`.
- ~~**Q6. Distribution.**~~ Decided: Docker Compose and `make` targets; see the design log.

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
9. Evaluation (retrieval: recall@k and MRR; generation: separate design). A demonstration, not for tuning.

| Stage | Decision | Why |
|---|---|---|
| UI | Terminal only, rendered with Rich (Textual only if Rich feels cramped). The core (ingest, retrieval, agent) has no UI code, so a web UI over AG-UI can come later. | Lighter to build and run; the RAG stages are the hard part. |
| Diagrams | The agent draws simple text/markdown diagrams, not Mermaid. | A terminal cannot render Mermaid. |
| Corpus | Docs (book, guides, specs), `CHANGELOG.md` and `examples/`. Not the skill, not source docstrings (for now). | The changelog answers "what changed in version X"; examples ground code generation. |
| Versions | Only release tags (`vX.Y.Z`) are indexed; anything else is rejected. The chat defaults to the latest indexed release. | The docs then always match what users have installed from PyPI. |
| Changelog | One chunk per release entry, with the version it describes in the metadata (separate from the docs version tag). | "What changed in 0.2?" matches the right entry. |
| Examples | An example directory (README plus code) is one unit; book code stays attached to the chapter that cites it. | Code only makes sense beside its explanation. |
| Parsing | LlamaIndex `MarkdownNodeParser` after a cleaning step: strip nav blocks and the "docs for" badge, keep Mermaid blocks, lift `<!-- code: ... -->` markers into a `code_paths` metadata field. Each node carries layer, title, path, version, header path, and a citation URL built from the tag, path and heading anchor (`github.com/<repo>/blob/<tag>/<path>#<anchor>`). | Spike on `v0.1.0`: 527 nodes, no broken code fences, all code paths resolve. |
| Exclusions | Maintainer docs (`releasing.md`, `development.md`), `book/SUMMARY.md`, `book/STYLE.md`, and `examples/doclearn/samples/` (sample data). | They describe maintaining featherweight or are noise, not usage. |
| Changelog cleaning | Commit hashes and commit links are stripped; section headings and commit titles stay. | Hashes are noise for embeddings. |
| Chunking | Sections of 1,000 to 1,500 characters, split at paragraph boundaries, fenced code never split. Sections under about 200 characters merge into a neighbour. No overlap; each chunk stores `prev_id` and `next_id` so retrieval can pull in a neighbour. Breadcrumb, page title and layer are metadata that is included in the embedded text (`url`, `code_paths`, ids are not). Changelog: one chunk per release entry. Examples: one chunk per example directory. | Headings give natural boundaries, so overlap adds little. |
| Evaluation | Retrieval evals are built: `evals/retrieval.yaml` (20 questions with the pages that answer them, chosen from the docs' titles and headings) scored with recall@k and MRR by `make eval`, locally with no model calls. Result on v0.1.0: recall@1 0.80, @3/@5/@10 0.95, MRR 0.875; the one miss is "What changed in the first release?" (the single changelog chunk). Generation evals are still to do and need real model calls. Both are a demonstration, as before. We do not tune the pipeline against them. | Shows that evals are available without turning the project into an optimisation exercise. |
| Embedding | EmbeddingGemma 2, text-only 270M variant, run by Ollama (`embeddinggemma-2:270m`), which uses GGUF and llama.cpp underneath. The app calls it over HTTP (`/api/embed`). No PyTorch, no compiling. Facts from the model card: 8,192-token context, 768 native dimensions, Matryoshka sizes 768/512/256/128. We store 512-dimension vectors (the second-largest, chosen to demonstrate MRL): slice the 768 vector, then L2-normalise it. Queries and documents use the same dimension. | MRL here is a demonstration, not an optimisation. 512d is almost lossless on the model card's benchmarks (MTEB multilingual 61.17 vs 61.36). |
| Embedding prompts | The model needs task prefixes, and Ollama does not add them. Documents: `title: {breadcrumb} ({layer}) \| text: {content}`. Queries: `task: search result \| query: {query}`. The document prefix replaces the earlier "metadata block" idea. | The model was trained with these formats; omitting them lowers quality. |
| Embedding precision | Never float16 (the model gives NaN or degraded vectors). Check that the Ollama build returns sane vectors (no NaN, unit-length after normalising). | Warning on the model card. |
| Chunk ceiling | The 8K-token context removes the earlier worry about the 12 KB changelog entry and the 6-9 KB examples: they fit. Whole examples are embedded as one chunk. | Context is large enough. |
| Index | LanceDB, embedded, stored on disk. One table holds all versions; retrieval filters on `version`; `drop <version>` deletes by filter. LanceDB also gives full-text search for hybrid retrieval later. | No server to run, one directory the user owns. |
| Data directory | The user controls where data lives: a config file (written by a first-run `fw-qna init`, with a `--data-dir` flag and an `FW_QNA_HOME` env var overriding it). Holds the LanceDB directory and the downloaded model file. In Docker it is a mounted volume. | The index and the model are the user's, and survive upgrades. |
| Runtime | Everything runs in Docker Compose, driven by `make`: an `ollama` service (the embedding model, pulled once into a volume), an `ingest` job and the `chat` app. The chat is interactive through `docker compose run --rm chat`. Targets: `make up`, `make ingest REF=v0.1.0 SOURCE=<git url or path>`, `make chat`, `make versions`, `make drop REF=...`. Ingestion is a make step, not a Python command the user types. | A demo app: one command to run, no local Python setup, no compiler. The Python package still has its own CLI entry points inside the containers. |
| Data | A bind-mounted `./data` directory holds the LanceDB index and Ollama's model store, so the user controls and keeps it. The `FW_QNA_HOME` / `--data-dir` setting becomes the container's mount point. | Same goal as before: the user owns the data. |
| Retrieval | Hybrid search: BM25 (LanceDB full-text) plus vector similarity on the 512d embeddings, merged with reciprocal rank fusion. No reranking. Version filter on every search: the latest indexed release unless the user asks for another (session `/version`, or a per-call argument). Examples capped at one or two per search. | Identifiers like `JobWorker` suit BM25; questions suit embeddings. |
| `search_docs` tool | `search_docs(query, keywords=None, layer=None, version=None, top_k=5)`. `query` is natural language, embedded for the vector side. `keywords` is an optional list of exact identifiers used only for BM25 (falls back to `query`). Returns text, breadcrumb, citation URL and `code_paths` per hit. Neighbour expansion via `prev_id`/`next_id` is decided with the agent. | Lets the model give each half of the search the input it works best with. |
| Code checking | None. Generated code is shown as the model wrote it. | Keeps the demo simple. |
| Code warning and drafts | Every answer with code ends with a fixed italic warning that the code is untested and may not work; the model never claims it works. When the docs do not cover what was asked (for example a Postgres job queue), the model says so in one sentence and still writes an illustrative example, built on the documented interfaces, marking what is documented and what is its own design. It never invents featherweight API. This is prompt-only: a model can still forget the warning. | The code is an idea of how things could look, not a promise. |
| Chat agent | `DocsChat(StreamingAgent)` on `Claude(model="claude-haiku-5-5", effort="low")`, with a strict system prompt and the `search_docs` tool. No output type. The app calls `runner.stream()` with `ChatInput.from_langchain(history + user message)` and reads the AG-UI events: text deltas for the answer, tool-call events for the "searching" line, tool results for the sources. | Per the featherweight skill: a chat agent that streams is a `StreamingAgent`. |
| History | All messages are kept in memory for the session (`history += [user_message, *run.new_messages]`, saved in a `finally` after the stream closes). Nothing is stored across sessions. | Simple; nothing is lost mid-conversation. |
| Context size | Track the size of the context and, near a threshold (80% of a configurable limit), offer to trim: keep the last few turns (default 4) and drop the rest, whole turns at a time so tool calls keep their results. `run.usage.input_tokens` sums every model call in a turn, so it overstates the context; use the input tokens of the last model call (from the last assistant message's usage metadata if featherweight keeps it, otherwise a character-count estimate). | Search results are large, so long chats grow fast. The model's context limit is a setting. |
| Stopping | Ctrl-C cancels the current answer (`run.cancel()`); the partial answer stays in the history. `/exit` or Ctrl-D quits. | From the skill's streaming reference. |
| Citations | `search_docs` numbers each hit with a session-wide reference `[n]`. The prompt requires `[n]` after every claim, paragraph or code block that relies on a hit. The UI lists only the sources cited in the answer, with breadcrumb and the GitHub link at the tag; uncited hits show dimmed as "also searched"; a cited number no search returned is flagged unverified. Titles and links come from tool results, never from the model's text. | Shows what was used, not only what was retrieved, without enforcement. |
| Terminal interface (built) | Rich plus prompt_toolkit, no Textual. The answer is rendered as markdown while it streams: the live view shows only the last screenful (a live display taller than the terminal repaints and repeats text), and the whole answer is printed once, normally, when it is complete. Colors are hex codes with defaults, changeable in `config.yaml`. The default context limit is 100,000 tokens, changed live with `/context`. The defaults (context limit, colors) live in a commented `defaults.yaml` that ships with the package; it is copied to `<data dir>/config.yaml`, which is read on every start, and `/context` rewrites only that file's `context_limit` line. Invalid values fall back to the defaults; a file that is not valid YAML is reported, not ignored. `/save` writes into `<data dir>/saved` (the container's filesystem is not kept), `/copy` uses the OSC 52 terminal escape, and `/exit` or Ctrl-D leaves. | Decided with the user. |
| Terminal interface | A banner (name, version indexed, model, commands), clearly separated `You` and `fw-qna` turns, a spinner with the search queries, markdown rendering with highlighted code, sources under each answer. Commands: `/exit`, `/version`, `/sources`, `/save`, `/copy`, `/clear`, `/help`. | A clear starting point and clear user and assistant separation. |
| Skills | Ingestion also takes `skills/` from the same release tag and installs it into `<data dir>/skills/<tag>/<name>/` with a `source.json` (repo URL and tag), replacing the earlier copy; `drop` removes it. `make ingest` pulls from GitHub by default (the repo is public), and a local clone still works. The chat agent gets the skill of the release it answers from (issue #31). | The skill and the docs always match, and no local clone is needed. |
| Chat skill | The chat agent gets the featherweight skill of the release it answers from (`skills=[...]`, so featherweight adds `get_skill`), rebuilt on `/version`. The prompt: the skill is for how to write featherweight code, `search_docs` is for facts and citations; its reference files duplicate the docs, so open one only for a pattern the skill points to; the chat cannot run anything, so ignore instructions to run, install, test or ask permission; the untested warning stays; say when the skill was used, with no `[n]`. The UI shows "reading the skill" while it loads, and lists the skill files read under Sources with GitHub links at the tag (not numbered). | A showcase of featherweight's skills (progressive disclosure), and better code. |
| Chat model | Claude Haiku 5.5 (`claude-haiku-5-5`) for the demo. Any featherweight-supported model can be swapped in. | Shows featherweight's provider flexibility. |
| Retrieval | A `search_docs` tool the agent chooses to call. Not enforced: no output validation for citations. Grounding comes from a clear tool description and a strict system prompt (any question about featherweight must be answered from `search_docs`, never from memory). | Keeps the demo simple, and is the standard RAG shape. If evals show the model skipping the tool, we revisit (a typed `kind` field with `check_output`, see the discussion). |
| Embeddings | EmbeddingGemma 2 through Ollama over HTTP, so local, with no PyTorch. | Mixing a local embedder with a hosted chat model is itself a good demo. |
