# Architecture

RAG system for analysing annual reports. Python backend, web frontend, runs locally, data persists across restarts.

The key architectural decisions, with why and when to revisit each, are in README.md. This file has the details.

## Layers

Four layers, with the domain objects (see UBIQUITOUS_LANGUAGE.md) at the centre:

1. **Domain** (`domain.py`): Report, Passage, Evidence, Facts. Pydantic models plus their rules (e.g. `plain`, `Passage.search_text`). They import nothing from the app except `pdf.Block` and `pdf.PageBox`, the text a Passage is made of and the shape of a highlight.
2. **Generic tools** (`pdf/`, `search/`, `llm.py`, `storage.py`): each wraps one library or job. `pdf/` holds `models.py` (Block, PageBox, ExtractionError), `mistral_extractor.py` (the `PdfExtractor` interface and Mistral OCR) and `rasterizer.py` (page count and page images, with pdfium). `search/` holds `embedder.py` (the embedding model) and `index.py` (BM25 and the hybrid index). `storage.py` writes a file atomically. They know nothing about reports and import nothing from the app except `search.Vectors`.
3. **Use cases** (`reports/`, `facts/`, `chat/`): `ReportService` adds and processes a report; `Retriever` embeds and searches its Passages. `FactExtractor` reads Facts out of a report and stores nothing. `ChatService` extracts what a Question asks about, finds the matching reports' Facts, answers from them and stores the Conversation.
4. **HTTP** (`routers/`): parse input, call `ReportService` or `ChatService`, map their errors to a status and an `ErrorCode`; the UI words the code. A route that only reads what upload stored, with no logic on top, reads `ReportRepository` directly.

Imports point one way: `routers → chat → reports → facts → domain + generic tools`.
```text
.
├── README.md, ARCHITECTURE.md, UBIQUITOUS_LANGUAGE.md
├── docs/                       # the README's screenshots; how-it-works.html is the diagram's source
├── docker-compose.yml          # backend on :8000, frontend (nginx) on :8080
├── .env.example                # ANTHROPIC_API_KEY, MISTRAL_API_KEY and optional settings
├── models/fastembed/           # the embedding model, copied into the backend image
├── samples/                    # annual report PDFs to try
├── backend/
│   ├── Dockerfile, pyproject.toml, uv.lock
│   ├── data/                   # runtime: reports/ and conversations/ (git-ignored)
│   ├── scripts/                # migrate_field_names.py: one-off rename of old stored fields
│   ├── tests/                  # pytest; conftest.py fakes Claude, Mistral, the embedder and the job queue
│   └── src/report_analyst/
│       ├── main.py             # the FastAPI app, routers, logging; start-up fails interrupted jobs
│       ├── settings.py         # AppSettings from environment variables
│       ├── domain.py           # Report, Passage, Evidence, Fte, SustainabilityGoal, Facts
│       ├── llm.py              # AnthropicLLM: structured output (Instructor) or cited text
│       ├── storage.py          # write_atomic: write to a temporary file, then rename
│       ├── search/
│       │   ├── embedder.py     # Embedder: bge-small via fastembed (ONNX), passages and queries
│       │   └── index.py        # BM25 + HybridIndex: keyword and embedding search, fused by rank
│       ├── pdf/
│       │   ├── models.py       # Block (heading/text/table, with its PageBox), ExtractionError
│       │   ├── mistral_extractor.py  # PdfExtractor interface; MistralExtractor (Mistral OCR API)
│       │   └── rasterizer.py   # count_pages, render_pages (pdfium, one lock)
│       ├── reports/
│       │   ├── service.py      # ReportService: add (checks, duplicates) and the background job
│       │   ├── repository.py   # ReportRepository: one folder per report
│       │   ├── retriever.py    # Retriever: embeds Passages, searches them with a cached index
│       │   ├── splitting.py    # split_into_passages: Blocks into Passages for search
│       │   └── errors.py       # what can go wrong when adding a report
│       ├── facts/
│       │   ├── extractor.py    # FactExtractor: topic searches, then one Claude call
│       │   └── model_output.py # the Facts as Claude writes them; checks each quote in its Passage
│       ├── chat/
│       │   ├── service.py      # ChatService: the three steps in order, every check between them
│       │   ├── filtering_fields.py   # step 1: extract_filtering_fields (Fact, Company-year pairs)
│       │   ├── relevant_facts.py     # step 2: find_reports, collect_relevant_facts (no model)
│       │   ├── answer_generation.py  # step 3: generate_answer, citing the Facts
│       │   ├── repository.py   # ConversationRepository: one JSON file each
│       │   └── models.py       # ReportRef, Answer, Turn, Conversation, ChatReply
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
        ├── App.test.tsx        # vitest: the app staying up through a chat
        ├── api/                # import from "api": index.ts re-exports the two below
        │   ├── client.ts, api.gen.ts  # backend calls; types generated from the OpenAPI schema
        │   └── messages.ts     # the user's wording for every error, failure and Not Found code
        ├── chat/
        │   └── ChatPanel.tsx   # useChat, ChatComposer, ChatThread
        ├── reports/
        │   ├── ReportsDrawer.tsx  # the list with filters, or one report with retry
        │   ├── ReportView.tsx  # one ready report: its facts beside the page with the evidence
        │   ├── UploadDialog.tsx   # the "Add a report" popup and its duplicate question (+ test)
        │   └── options.ts      # labels and options shared by the filters and the chat scope
        └── ui/                 # the component library: tokens.css, one .tsx + .css per area
```

## Chat

Chat answers only what processing extracted, the FTE and the Sustainability Goals. `ChatService._answer_question` runs three steps, one module each, and makes every check between them; a check that fails raises `QuestionNotAnsweredError`, which `ask` stores as a Not Found with its reason. Covering other topics by searching the Passages is a next step in README.md.

The three steps:

1. **Extract the filtering fields** (`filtering_fields.extract_filtering_fields`, structured output through Instructor). Claude gets the Question, the last three Questions and the stored reports (Company and year), and returns `FilteringFields`: the `fact` asked about (`fte`, `sustainability_goals`, or null for anything else) and the `company_year_pairs`. Since it sees the stored reports, it writes their Companies as stored ("ABN" is "ABN AMRO"); it gives a year only if the Question names one; a follow-up keeps the earlier Company. No fact is `unsupported_topic`; no pair is `no_company_named`.
2. **Find the relevant Facts** (`relevant_facts.py`, in code, no model). `find_reports` matches each pair to the stored reports by Company (ignoring case) and year; a pair without a year is that Company's latest stored report. It returns the pairs with no report rather than raising, so `_answer_question` makes the check. A pair with no report is `no_matching_report`, naming it in `missing`; reports all still processing or failed are `report_not_ready`. The Facts of the kind asked about, from the ready reports, are the relevant Facts; none is `not_in_report`.
3. **Generate the answer** (`answer_generation.py`, citations). Each relevant Fact is one document: the title names the report, page and fact ("ABN AMRO 2025, page 57: Sustainability goal: Net zero, deadline 2050", from `SustainabilityGoal.as_string`) and the content is its verbatim quote. The prompt lists the reports asked about with what was found in each; it sets no length or layout, only that the answer is plain text and comes from the documents. A cited Fact becomes Evidence with its own page and boxes, as in the report view. An answer citing nothing is `not_in_report`, whatever its text says.

The UI shows the reports a Question was matched to under it. There are no Company or year selects: the Question, or the earlier ones for a follow-up, says which reports. The UI words every reason. Conversations are JSON files, so they survive a restart; the browser keeps the open one's id to show it again. Files stored before this still load: the old `scope` is ignored and `reports` defaults to empty.

## Frontend

- **API contract.** The backend's Pydantic models are the source of truth. `npm run gen:api` dumps FastAPI's OpenAPI schema to `frontend/openapi.json` and generates `src/api/api.gen.ts`; `api/client.ts` re-exports the types under domain names. Change a backend model, run `gen:api`, and `npm run typecheck` shows every place the UI must follow.
- **Base path.** The browser calls `/api/uploads`; Vite (dev) and nginx (Docker) strip `/api` and forward to the backend, so there is no CORS.
- **Design tokens.** All raw values live in `ui/tokens.css`. Each component file in `ui/` has its stylesheet next to it (`chat.css`, `list.css`, …), using only tokens, enforced by stylelint. Screens compose `ui/` components and never write CSS or class names. A new look means a new component in `ui/`, not a style in a screen.
- **Screens.** `App.tsx` lays out the page and holds the state the chat and the drawer share; `chat/ChatPanel.tsx` (the chat, with `useChat`) and `reports/ReportsDrawer.tsx` (the list and one report) hold their own.

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

A database (PostgreSQL, see Next steps in README.md) comes when more than one process updates report statuses, or when conversations need searching or sharing. Not before: reports, passages and vectors as files keep one owner per report folder.

## Deliberately skipped

- No task queue (arq, RQ, Celery): one in-memory worker thread, and a restart fails the running job (the user retries). Add one when jobs must survive restarts or run on more than one worker.
- No interfaces (ABCs) for the LLM or the embedder. Each has one implementation, so the service takes `AnthropicLLM` and `Embedder` directly; tests swap them through `get_llm` and `get_embedder`. To add a second provider, extract an ABC from the class's public methods and change one line in `routers/dependencies.py`.
- `PdfExtractor` is an ABC with one real child, `MistralExtractor`; tests swap in a local fake that reads the text layer. Children implement only `extract`, returning Blocks with their boxes. Page counting and rendering are plain functions in `pdf/rasterizer.py` (pdfium), the same whatever extracts the text. `routers/dependencies.py` builds the extractor once. README.md lists the extractors we tried before.

## Ubiquitous language

Report, Passage, Evidence, Facts. See UBIQUITOUS_LANGUAGE.md.
