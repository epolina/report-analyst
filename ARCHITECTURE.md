# Architecture

RAG system for analysing annual reports. Python backend, web frontend, runs locally, data persists across restarts.

## Layers

Four layers, with the domain objects (see UBIQUITOUS_LANGUAGE.md) at the centre:

1. **Domain** (`domain.py`): Report, Passage, Evidence, Facts. Pydantic models plus their rules (e.g. `plain`, `Passage.search_text`). They import nothing from the app except `pdf.Block` and `pdf.PageBox`, the text a Passage is made of and the shape of a highlight.
2. **Generic tools** (`pdf/`, `index.py`, `embedder.py`, `llm.py`, `storage.py`): each wraps one library or job. `pdf/` holds `models.py` (Block, PageBox, ExtractionError), `mistral_extractor.py` (the `PdfExtractor` interface and Mistral OCR) and `rasterizer.py` (page count and page images, with pdfium). `storage.py` writes a file atomically. They know nothing about reports and import nothing from the app except `embedder.Vectors`.
3. **Use cases** (`reports/`, `facts/`, `chat/`): `ReportService` adds and processes a report; `Retriever` embeds and searches its Passages. `FactExtractor` reads Facts out of a report and stores nothing. `ChatService` answers a Question from the reports in scope and stores the Conversation.
4. **HTTP** (`routers/`): parse input, call `ReportService` or `ChatService`, map their errors to a status and an `ErrorCode`; the UI words the code. A route that only reads what upload stored, with no logic on top, reads `ReportRepository` directly.

Imports point one way: `routers → chat → reports → facts → domain + generic tools`.

## Package layout

```text
.
├── README.md, ARCHITECTURE.md, API.md, UBIQUITOUS_LANGUAGE.md, PRODUCT.md
├── docker-compose.yml          # backend on :8000, frontend (nginx) on :8080
├── .env.example                # ANTHROPIC_API_KEY, MISTRAL_API_KEY and optional settings
├── models/fastembed/           # the embedding model, copied into the backend image
├── samples/                    # annual report PDFs to try
├── backend/
│   ├── Dockerfile, pyproject.toml, uv.lock
│   ├── data/                   # runtime: reports/ and conversations/ (git-ignored)
│   ├── tests/                  # pytest; conftest.py fakes Claude, Mistral, the embedder and the job queue
│   └── src/report_analyst/
│       ├── main.py             # the FastAPI app, routers, logging; start-up fails interrupted jobs
│       ├── settings.py         # AppSettings from environment variables
│       ├── domain.py           # Report, Passage, Evidence, Fte, SustainabilityGoal, Facts
│       ├── embedder.py         # Embedder: bge-small via fastembed (ONNX), passages and queries
│       ├── index.py            # BM25 + HybridIndex: keyword and embedding search, fused by rank
│       ├── llm.py              # AnthropicLLM: structured output (Instructor) or cited text
│       ├── storage.py          # write_atomic: write to a temporary file, then rename
│       ├── pdf/
│       │   ├── models.py       # Block (heading/text/table, with its PageBox), ExtractionError
│       │   ├── mistral_extractor.py  # PdfExtractor interface; MistralExtractor (Mistral OCR API)
│       │   └── rasterizer.py   # page_count, render_pages (pdfium, one lock)
│       ├── reports/
│       │   ├── service.py      # ReportService: add (checks, duplicates) and the background job
│       │   ├── repository.py   # ReportRepository: one folder per report
│       │   ├── retriever.py    # Retriever: embeds Passages, searches them with a cached index
│       │   ├── splitting.py    # split_into_passages: Blocks into Passages for search
│       │   └── errors.py       # what can go wrong when adding a report
│       ├── facts/
│       │   ├── extractor.py    # FactExtractor: topic searches, then one Claude call
│       │   └── answer.py       # the Facts as Claude writes them; checks each quote in its Passage
│       ├── chat/
│       │   ├── service.py      # ChatService: scope, search, Claude with citations; resolve_scope
│       │   ├── repository.py   # ConversationRepository: one JSON file each
│       │   └── models.py       # Scope, Answer, Turn, Conversation, ChatReply
│       └── routers/
│           ├── dependencies.py # builds settings, tools, repositories and services
│           ├── errors.py       # ErrorCode and the error bodies; ApiError and its handler
│           ├── uploads.py      # POST /uploads
│           ├── reports.py      # GET /reports, /reports/{id}, …/pages/{n}; POST …/retry
│           ├── chat.py         # POST /chat, GET /conversations/{id}
│           └── health.py       # GET /health
└── frontend/
    ├── Dockerfile, nginx.conf  # built app served by nginx, /api forwarded to the backend
    ├── package.json            # npm run dev | check | gen:api
    ├── openapi.json            # generated from the backend: npm run gen:api
    └── src/
        ├── main.tsx            # mounts App
        ├── App.tsx             # the layout, the report list and the drawer; shared state
        ├── ChatPanel.tsx       # useChat, ChatComposer, ChatThread
        ├── ReportsDrawer.tsx   # the list with filters, or one report with retry
        ├── ReportView.tsx      # one ready report: its facts beside the page with the evidence
        ├── UploadDialog.tsx    # the "Add a report" popup and its duplicate question
        ├── api.ts, api.gen.ts  # backend calls; types generated from the OpenAPI schema
        ├── options.ts          # labels and options shared by the filters and the chat scope
        ├── messages.ts         # the user's wording for every error, failure and Not Found code
        ├── *.test.tsx          # vitest: the upload dialog, and the app staying up through a chat
        └── ui/                 # the component library: tokens.css, one .tsx + .css per area
```

## Chat

Chat: a Question's Company and year come from its text when it names a stored one ("How much did SHELL spend … in 2025?"), otherwise from the selects under the composer; two named means a comparison, so that field searches all. The UI shows the scope searched and sets the selects to it, so a follow-up keeps it. Follow-ups also get the last three Turns in the prompt, and the previous Question joins the search query. Not Found is an Answer with a reason (`not_in_report`, `report_not_ready`, `no_report`).

Chat quotes come from the API's citations, not from the model's own copy: each Passage is a document, and the API returns the exact span cited, so a quote can't be misquoted. Prose is cited by sentence; a Passage with a Markdown table goes in one line per block, so Claude cites the rows it used. An answer citing nothing is Not Found, whatever its text says. Citations don't combine with structured output, which is why facts (which need typed fields) still use Instructor and check their quotes themselves. Conversations are JSON files, so they survive a restart; the browser keeps the open one's id to show it again.

## File roles

- **domain.py**: the domain objects as Pydantic models. Rules live as methods here (e.g. a quote must occur in a Passage on its page). No vendor types.
- **Generic tool files**: one library each, plain types in and out (`bytes`, `str`, `Vectors`, row numbers). They raise their own errors (`ExtractionError`, `LLMError`).
- **reports/service.py**: the use cases. It orchestrates the domain, the repository and the tools, and turns tool errors into domain errors from `errors.py`. It knows nothing about HTTP.
- **reports/repository.py** and **chat/repository.py**: storage. Each alone knows its layout (folder and file names). Callers pass domain objects, never paths.
- **routers/**: one file per resource. A route parses input, calls the service and maps its errors to status codes. Plain reads of stored files go to the repository instead.
- **routers/dependencies.py**: the only place that builds the tools, the repository and the service. Values such as directories come from `AppSettings`, never from literals here.

## Rules

- Generic tools never import `domain`, `facts` or `reports`. If one needs a domain word, it belongs in the service.
- `facts/` gets search as a function argument, so it never imports `reports`. Chat imports `reports` (it needs the report list for its scope); `reports` never imports chat.
- Each package's `__init__.py` (`reports`, `chat`, `facts`, `pdf`) lists its public names under `__all__`. Code outside imports from the package (`from report_analyst.reports import ReportService`); code inside imports its modules by absolute path.
- The original upload name is kept in `metadata.json` for reference only. It is never shown and never used as a path.

## Frontend

- **API contract.** The backend's Pydantic models are the source of truth. `npm run gen:api` dumps FastAPI's OpenAPI schema to `frontend/openapi.json` and generates `src/api.gen.ts`; `api.ts` re-exports the types under domain names. Change a backend model, run `gen:api`, and `npm run typecheck` shows every place the UI must follow.
- **Base path.** The browser calls `/api/uploads`; Vite (dev) and nginx (Docker) strip `/api` and forward to the backend, so there is no CORS.
- **Design tokens.** All raw values live in `ui/tokens.css`. Each component file in `ui/` has its stylesheet next to it (`chat.css`, `list.css`, …), using only tokens, enforced by stylelint. Screens compose `ui/` components and never write CSS or class names. A new look means a new component in `ui/`, not a style in a screen.
- **Screens.** `App.tsx` lays out the page and holds the state the chat and the drawer share; `ChatPanel.tsx` (the chat, with `useChat`) and `ReportsDrawer.tsx` (the list and one report) hold their own. `mockup/combined/b-chat-first.html` is the reference layout.

## Persistence

Files. Each report is a folder in `REPORTS_DIR` (default `data/reports`): `upload.pdf`, `passages.json`, `embeddings.npy` (row *i* embeds passage *i*), `metadata.json`, `page-images/` and `facts.json` (saved while processing). Each file is written to a temporary name and renamed (`storage.write_atomic`). Conversations are one JSON file each in `CONVERSATIONS_DIR`. `create` writes `upload.pdf` and then `metadata.json` (with the status), and clears a replaced report's derived files; processing adds the rest with `save_contents`. So a report with metadata always has its PDF, but its pages and search index only once it's done `processing`. `ReportRepository` is the only code that knows these names.

## Background processing

`POST /uploads` runs only the quick checks (PDF magic bytes, duplicates, pdfium can open it), stores the PDF and answers `202`. `ReportService._process` then runs on a module-level `ThreadPoolExecutor(max_workers=1)`: text with Mistral OCR, Passages, embeddings, page images, then the Facts, all as `processing`, then `success`. Any error sets `failed` with a `failure` code; the job never raises, since the executor would swallow it. Each step logs how long it took.

Nothing is `async`, on purpose. Most of the processing time is CPU work (embedding, rendering), which `async` doesn't speed up and would have to push onto a thread anyway. Routes are plain `def`, which FastAPI runs on its thread pool, so a chat question waiting on Claude holds one thread, not the server. Async clients would pay off with many users at once waiting on the LLM, not for one analyst on one machine.

- **One at a time.** Two jobs would compete for the CPU (page rendering, embedding), so the executor has one worker and a second job waits its turn. The UI offers one upload or retry at a time anyway. Replacing a report that is still processing gets `409`: its job would otherwise save the old PDF's contents over the new one.
- **Start-up recovery.** The queue is in memory, so a restart loses the running job. The lifespan in `main.py` marks reports left `processing` as failed ("Processing was interrupted."), and the user retries them. This assumes one app process: with several uvicorn workers, one would fail the others' jobs.
- **Retry** (`POST /reports/{id}/retry`) sets a failed report back to `processing` and queues it on its stored PDF.
- **Tests** swap the executor for one that runs jobs straight away (`conftest.py`), or holds them to look at a processing report.

Search runs in memory: `Retriever.search` loads a report's Passages, embeddings and a BM25 index on first use and keeps them, keyed by report id and when its `passages.json` was saved, so a replaced or retried report is reloaded. About 2 MB of vectors per 300-page report.

SQLite comes when more than one process updates report statuses, or when conversations need searching or sharing. Not before: reports, passages and vectors as files keep one owner per report folder.

## Deliberately skipped

- No task queue (arq, RQ, Celery): one in-memory worker thread, and a restart fails the running job (the user retries). Add one when jobs must survive restarts or run on more than one worker.
- No `domain/` or `application/` folders. Split a file past about 300 lines.
- No Company aggregate: the Company is a string on the report. A Company keeps the spelling it was first entered with, matched ignoring case ("shell" is stored as "Shell"); different names for one Company ("Royal Dutch Shell") aren't merged.
- No auth or multi-user.
- No interfaces (ABCs) for the LLM or the embedder. Each has one implementation, so the service takes `AnthropicLLM` and `Embedder` directly; tests swap them through `get_llm` and `get_embedder`. To add a second provider, extract an ABC from the class's public methods and change one line in `routers/dependencies.py`.
- `PdfExtractor` is an ABC with one real child, `MistralExtractor`; tests swap in a local fake that reads the text layer. Children implement only `extract`, returning Blocks with their boxes. Page counting and rendering are plain functions in `pdf/rasterizer.py` (pdfium), the same whatever extracts the text. `routers/dependencies.py` builds the extractor once. README.md lists the extractors we tried before.

## Ubiquitous language

Report, Passage, Evidence, Facts. See UBIQUITOUS_LANGUAGE.md.
