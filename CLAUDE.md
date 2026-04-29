# EFTA — Epstein Files Tracking & Analysis

> Project context for Claude. This file orients you to what's been built, why decisions were made, and how to work effectively in this repo.

## What this project is

EFTA is an AI-powered analysis pipeline for **publicly released DOJ Epstein case documents** (https://www.justice.gov/epstein/doj-disclosures). The goal is to extract structured information from photos, scanned documents, court records, and emails, then make it searchable on a public website — while protecting victim privacy.

**Owner's primary research interest:** identifying *other perpetrators and associates* connected to Jeffrey Epstein, not Epstein/Maxwell themselves.

## Privacy is non-negotiable

- **Victim names NEVER appear in public data.** Use the numbered system: `victim_00001`, `victim_00002`, etc.
- The `VictimTracker` (`pipeline/src/pipeline/privacy/victim_tracker.py`) maintains a private encrypted mapping (AES-256, key in Secret Manager) so the same victim gets the same number across documents.
- The `Redactor` (`pipeline/src/pipeline/privacy/redactor.py`) audits all extracted data for victim name leaks and redacts them.
- Gemini Vision is prompted to **refuse to identify private individuals or minors**, but DO identify public figures (Epstein, Maxwell, named defendants, politicians, celebrities) since that's the whole point.

## Current state (2026-04-11)

### Done
- **Data Set 1 fully processed:** 3,131 photos analyzed with vision pipeline, 5 properties identified, 266 exhibits grouped, all photos have multimodal embeddings ready for similarity search.
- **Local zero-cost pipeline built and validated** on a 20-doc Set 8 sample (2026-04-13). End-to-end works: download → pypdf → chunk → local embed (BGE-small) → SQLite (FTS5 + sqlite-vec) → entities (spaCy + regex) → FastAPI search/browse. See "Local pipeline" section below.
- **Sets 8-11 fully ingested (2026-04-21).** ~1.15 million documents downloaded, text-extracted with pypdf ($0 cost), and raw PDFs archived to Time Capsule. See details below.
- **Cost so far:** $18.43 of $300 GCP credit. Sets 8-11 ingest cost $0 (all local).

### Sets 8-11 ingest results (2026-04-21)

| Data Set | URLs Discovered | Docs Ingested | Download Fails | Extract Fails | PDFs on TC1 | Text Chars |
|---|---|---|---|---|---|---|
| Set 8 | 10,494 | 10,495 | 0 | 0 | 1.8 GB | — |
| Set 9 | 530,456 | ~530K | 8 | 33 | 95 GB | — |
| Set 10 | 276,372 | 276,337 | 35 | 0 | 52 GB | 775M |
| Set 11 | 328,567 | 328,540 | 28 | 0 | 27 GB | 506M |
| **Total** | **1,145,889** | **~1,145,372** | **71** | **33** | **176 GB** | — |

- **99.99% success rate** across 1.15M documents.
- URL discovery used the Wayback Machine (`wayback_urls.py`) to bypass DOJ Akamai's paginated-listing rate limit. `--max-pages 15000` needed for Sets 9-11 (Set 8 only has ~221 listing pages).
- Text JSONs on SSD: `/Volumes/externalSSD256/EFTA/text/set-N/`
- Raw PDFs on Time Capsule: `/Volumes/Ryan/EFTA/pdfs/set-N/` (176 GB of 2.7 TiB used)
- URL caches on SSD: `/Volumes/externalSSD256/EFTA/staging/urls-set-N.txt`
- `local_ingest.py` is fully resumable: skips docs where both JSON + PDF exist. Re-running is safe and will only retry failures.
- pypdf `PdfReadError` exceptions (malformed PDFs) are caught and recorded as `extract_fail` stubs so they don't crash the run.

### Survey results (other data sets)
- **Set 2** (~588 files): celebrity photos — Bill Clinton + Epstein together found in samples
- **Set 3** (~98 files): multi-page evidence + 98-page photo album with section labels (ZORRO/VEGAS, LSJ AERIALS, CLOUDS, PRAGUE, PAINTING)
- **Set 4** (~196): Palm Beach Police records (2006 fax logs)
- **Sets 5-7** (small): photos + a few long text docs
- **Set 12** (~200): DOJ legal memos including Maxwell prosecution memo

### Not yet built
- ~~Entity extraction + search index~~ — **DONE** (see Roadmap Phase 1)
- The website (Next.js frontend) — API is ready for it (see Roadmap Phase 2)
- LLM extraction on high-value docs (see Roadmap Phase 3)
- Cross-photo matcher, remaining data sets (see Roadmap Phase 4)

## Architecture

```
DOJ site → scraper → GCS → [vision OR ocr OR pypdf] → text/structured data
                              ↓
                         Gemini extraction (events, people, locations)
                              ↓
                       Property → Exhibit → Photo hierarchy
                              ↓
                       Firestore (collections: documents, events, people,
                       victims, locations, properties, exhibits,
                       image_elements, victim_identity_mapping)
```

## Pipeline modules

| Module | What it does |
|---|---|
| `scraper/sequential_scraper.py` | **PRIMARY scraper for sequential data sets.** Generates URLs directly (`EFTA00000001.pdf` ... `EFTA00003158.pdf`) bypassing rate-limited listing pages. |
| `scraper/doj_scraper.py` | Crawls listing pages for non-sequential data sets (3+). Has age verification cookie + exponential backoff for 403s. |
| `text_extraction/pdf_text_extractor.py` | **Free** PDF text extraction with pypdf. Use this first for any text-heavy data set. |
| `ocr/processor.py` | Document AI OCR for scans (paid: $1.50/1000 pages). |
| `ocr/audio_transcriber.py` | Speech-to-Text for `.wav`/`.mp3`/`.mp4` (untested). |
| `vision/processor.py` | Gemini 2.5 Flash for image-heavy PDFs (~$0.001/image). |
| `vision/embeddings.py` | Vertex AI multimodal embeddings (1408-dim, ~$0.0002/image). |
| `vision/property_resolver.py` | Fuzzy-matches FBI evidence card addresses to known Epstein properties. |
| `extraction/llm_extractor.py` | Gemini text extraction for events/people/locations (~$0.001/page). |
| `extraction/entity_resolver.py` | Dedupes extracted entities against existing Firestore records. |
| `privacy/victim_tracker.py` | Sequential victim IDs + encrypted identity mapping. |
| `privacy/redactor.py` | Audits extracted data for victim name leaks. |

## Jobs (entrypoints)

| Command | What it does |
|---|---|
| `python -m pipeline.jobs.run_scraper sequential 1 1 100` | Sequential download files 1-100 from Data Set 1 |
| `python -m pipeline.jobs.run_scraper data-set-3-files` | Crawl-mode download from Data Set 3 |
| `python -m pipeline.jobs.run_vision all 10` | Vision pipeline on all DOWNLOADED docs with 10 parallel workers |
| `python -m pipeline.jobs.run_ocr` | Document AI OCR on DOWNLOADED docs |
| `python -m pipeline.jobs.run_extraction` | Gemini text extraction on OCR_COMPLETE docs |
| `python -m pipeline.jobs.group_exhibits` | Build Property → Exhibit hierarchy from vision-complete docs |
| `python -m pipeline.jobs.survey_data_sets` | Sample 5 files from each remaining data set, describe with Gemini Vision |
| `python -m pipeline.jobs.probe_text_extraction` | Test pypdf success rate on Data Sets 8-11 |

## Local pipeline (zero-cost path for Sets 8-11)

Everything below runs on the owner's Mac + external SSD with no ongoing
GCP costs. Built to process the ~1.1M native-text PDFs in Sets 8-11 for
$0 instead of ~$250-400 with Vertex.

### On-disk layout
- **External SSD** (`/Volumes/externalSSD256/EFTA/`):
  - `staging/urls-set-N.txt` — cached listing URLs per data set
  - `text/set-N/<prefix>/<doc_id>.json` — extracted per-page text + metadata
  - `db/efta.sqlite` — the single searchable DB
- **Time Capsule** (`EFTA_TIME_CAPSULE_ROOT` in `.env`, currently
  `/Volumes/Ryan/EFTA/pdfs`) — raw PDF mirror. `local_ingest.py` writes each
  downloaded PDF here atomically (tmp → rename) in a `set-N/<prefix>/<doc_id>.pdf`
  layout mirroring the text JSONs. When the env var is unset or the mount is
  missing at startup the job logs a warning and skips the mirror. AFP write
  failures are logged per-file and don't fail the run.
- Override root with `EFTA_LOCAL_ROOT` env var. See `local_storage/paths.py`.

### Modules (all local, zero-cost)
| Module | What it does |
|---|---|
| `local_storage/paths.py` | Centralized SSD paths (env-overridable) |
| `local_storage/sqlite_store.py` | Schema + writes + keyword/vector search. Uses **APSW** (not stdlib sqlite3) because macOS Python disables `enable_load_extension`. |
| `embeddings/local_embedder.py` | Sentence-transformers wrapper, default `BAAI/bge-small-en-v1.5` (384-dim, 512-token context, MPS auto-detected). |
| `embeddings/chunker.py` | Page-aware chunker; long pages split on paragraph/sentence boundaries, every chunk keeps its `page_number`. |
| `entities/extractor.py` | spaCy NER (`en_core_web_sm`) for PERSON/ORG/GPE/LOC/DATE/NORP/FAC/EVENT plus regex for EMAIL/PHONE/MONEY. |
| `api/app.py` | FastAPI search/browse layer (endpoints below). |

### Local jobs (entrypoints)
| Command | What it does |
|---|---|
| `python -m pipeline.jobs.local_ingest 8 --workers 6` | Parallel-download + pypdf-extract every URL in `urls-set-8.txt` → text JSON on SSD, and (if `EFTA_TIME_CAPSULE_ROOT` is set) mirror the raw PDF to the Time Capsule. Resumable: skips when JSON+PDF both exist; status `mirror_only` when only the PDF is missing. |
| `python -m pipeline.jobs.local_ingest 8 --limit 20` | Same, but cap processed docs (use for tests). |
| `python -m pipeline.jobs.wayback_urls 8 [--max-pages 15000]` | Discover Set-N URLs from web.archive.org when DOJ's Akamai blocks paginated listings. Writes to `staging/urls-set-N.txt`. Default `--max-pages 250` is enough for Set 8 (221 pages), **too low** for Sets 9-11 which each span 8K+ pages. |
| `python -m pipeline.jobs.build_index 8` | Read text JSONs for Set 8, chunk + embed locally, write chunks + vectors to SQLite. Resumable. |
| `python -m pipeline.jobs.extract_entities 8` | spaCy + regex NER over text JSONs; write entity rows to SQLite. Resumable. |
| `python -m pipeline.jobs.build_index all` | Any of the above accept `all` to iterate every `set-*` dir. |
| `python -m pipeline.jobs.test_local_pipeline 8 5` | End-to-end smoke test on a 5-doc sample (downloads, does NOT use on-SSD archive). |

### Running the search API
```bash
cd ~/EFTA/pipeline
python3 -m uvicorn pipeline.api.app:app --reload --port 8000
```
(Use `python3 -m uvicorn` not bare `uvicorn` — the python.org installer
doesn't put its scripts dir on PATH, so `uvicorn` won't be found.)
Then `http://127.0.0.1:8000/docs` for Swagger UI, `http://127.0.0.1:8000/` for stats.

Endpoints:
- `GET /` — health + DB counts
- `GET /search?q=...&type=keyword|semantic|hybrid&entity_type=GPE&entity_value=new+york&data_set=8&limit=20`
- `GET /doc/{doc_id}` — metadata + page list
- `GET /doc/{doc_id}/page/{n}` — full page text
- `GET /doc/{doc_id}/entities` — entities grouped by type
- `GET /similar/{chunk_id}` — nearest-neighbor chunks
- `GET /facets?top_n=25` — filter values per entity type (for UI dropdowns)

### Installation gotchas for the local stack
- Install the `local` extras: `pip install -e '.[local]'`. Requires `apsw`, `sqlite-vec`, `sentence-transformers`, `spacy`, `fastapi`.
- Separately: `python -m spacy download en_core_web_sm`.
- Stdlib `sqlite3` on the python.org / system Python builds is compiled **without** extension loading. That's why we use `apsw` — don't try to switch back to `sqlite3` without understanding this.

### Known quirks
- First BGE encode() loads a ~130 MB model; subsequent calls are fast. Cached under `~/.cache/huggingface`.
- BGE logs an `embeddings.position_ids UNEXPECTED` note on load. Harmless, ignore.
- APSW cursors must have `getdescription()` called **before** the row iterator is exhausted (we wrap this in `_rows_as_dicts`).

### Current DB state (2026-04-29)
```
documents:  1,068,106
pages:      2,235,584
chunks:     2,866,071   (768-dim Gemini embeddings)
entities:  34,187,107
DB size:   20 GB (on internal NVMe at ~/EFTA/db/efta.sqlite)
```
**Phase 1 complete.** All 1.15M docs from Sets 8-11 are fully searchable:
- **Entity extraction** (spaCy + regex): 34.1M entities — PERSON/ORG/GPE/DATE/EMAIL/PHONE/MONEY
- **Search index** (Gemini embedding-001, 768-dim via Vertex AI): 2.87M chunks with FTS5 keyword search + sqlite-vec semantic search
- Embedding cost: ~$42 of $1,000 GenAI credit (22.8 hours at 11.3 docs/s)
- DB location: internal NVMe (`EFTA_DB_DIR=/Users/ryanslay/EFTA/db`). Copy back to SSD when deploying.

## Critical technical findings (don't re-derive these)

### DOJ site quirks
- **Age verification gate:** All file URLs return 302 to `/age-verify` unless cookie `justiceGovAgeVerified=true` is set. Hardcoded in HTTP clients.
- **Pagination rate limits:** The DOJ Akamai CDN aggressively rate-limits listing pages (`?page=1+`) but does NOT rate-limit direct file URLs. Sequential scraper exploits this.
- **Sequential URL pattern (Data Sets 1, 2):** `https://www.justice.gov/epstein/files/DataSet%20{N}/EFTA{8-digit-zero-padded}.pdf`
- **Data Set 1 has exactly 3,158 files** (last is `EFTA00003158.pdf`).
- **Files stop being sequentially numbered starting Data Set 3.** Use crawl mode for those.

### Gemini model names
- `gemini-2.0-flash` and `gemini-2.0-flash-001` return **404 — deprecated.**
- **Use `gemini-2.5-flash`.** Set in `.env` as `GEMINI_MODEL`.

### Vision pipeline gotchas
- Gemini sometimes returns `null` for optional string fields. Pydantic schemas use `field_validator` with `mode="before"` to coerce None → "" or False. **Don't remove these validators.**
- `max_output_tokens=8192` is too small for multi-page documents. Use 65536.
- Image embedding model: `multimodalembedding@001`, dimension 1408, COSINE distance. Vector index already created on `documents.embedding`.

### Cost benchmarks
| Operation | Cost |
|---|---|
| pypdf text extraction | **$0** |
| Gemini 2.5 Flash vision | ~$0.001/image |
| Multimodal embeddings | ~$0.0002/image |
| Document AI OCR | $1.50/1000 pages |
| Gemini 2.5 Flash text extraction | ~$0.001/page |

**The owner cannot currently spend more money on this project.** Default to free options (pypdf) and only fall back to paid services when necessary. Always estimate cost BEFORE running expensive jobs.

### Active GCP credits (2026-04-13)
Two separate credits, each with different scopes. Always pick the right one for the job.

**1. Standard GCP trial — ~$280 remaining**
- Covers **everything on GCP**: GCS, Firestore, Cloud Run, Document AI, all Vertex AI including `text-embedding-004` and `multimodalembedding@001`, Pub/Sub, Secret Manager.
- Use this for: infra, storage, OCR (Document AI), Set 1 image embeddings, anything *not* covered below.

**2. Google Developer Program Premium GenAI Credit — $1,000, expires 2026-04-10 → 2027-04-10**
Scoped to two services only — **Gemini API** (`AEFD-7695-64FA`) and **Vertex AI** (`C7E2-9256-1C43`) — and within those, only specific SKUs.
- ✅ Covered:
  - All **Gemini text/image/audio/video generation** (2.0, 2.5, 3.0, 3.1 — Flash / Flash Lite / Pro)
  - **Gemini text embeddings** via `gemini-embedding-001` (EmbedContent + AsyncBatchEmbedContent)
  - **Context caching** SKUs (Caching Priority / Flex / Batch / Storage)
  - **Imagen 3/4** image generation (incl. Ultra, Upscale)
  - **Veo 2/3** video generation
  - **Lyria 3** audio generation
  - **Gemini Maps Grounding**
  - **Gemini Live / Bidi** streaming
- ❌ NOT covered (even though they're Vertex AI):
  - `text-embedding-004` (the standard Vertex text embed — different SKU)
  - `multimodalembedding@001` (the 1408-dim image embedder used in the Set 1 vision pipeline)
  - Document AI OCR
  - Vertex AI Search / Agent Builder
  - All infra (GCS, Firestore, Cloud Run, etc.)
- **Authoritative SKU list:** `public/genai_credit_skus.pdf` in this repo (108 pages, saved from Google's SKU group page).

**How to spend the $1,000 credit strategically**
1. **Rich LLM extraction pass** — Gemini 2.5 Flash on a filtered subset of high-value docs for the tags spaCy can't produce (colors, artwork descriptions, shipping labels, flight manifests). This is the biggest bang for buck.
2. **Optional embedding upgrade** — re-embed 1.1M Sets 8-11 docs with `gemini-embedding-001` (~$100-250) if we want better semantic quality than local BGE.
3. **Context caching** — if we make many passes over the same big prompt.

**When in doubt, check the SKU PDF first.** If a Vertex or Gemini operation is NOT in `public/genai_credit_skus.pdf`, it will bill against the $280 standard credit, not the $1,000 GenAI credit.

## Working with this repo

### Defaults to follow
- **Test small first.** Before kicking off any expensive job, run it on 5-10 documents and verify the output looks right. The owner has explicitly burned ~$14 of credit on bad runs and prefers verification over speed.
- **Commit and push to GitHub frequently.** Default to `git add -A && git commit && git push` whenever a chunk of work is functionally complete. The remote is `geo-neo-builds/EFTA`.
- **Present options, let the owner choose.** When there are multiple paths forward, list them with cost/effort tradeoffs rather than picking unilaterally.
- **Survey unfamiliar data sets first.** Use `survey_data_sets.py` and/or `probe_text_extraction.py` before processing.
- **Free text extraction is the default for text-heavy data sets.** Sets 8-11 should NEVER use Document AI OCR.

### Don't do these
- Don't run Document AI OCR on photo data sets — they extract ~13 chars per file because the content is visual. Use the vision pipeline instead.
- Don't try to crawl the DOJ paginated listing pages aggressively — they will 403 you. Use sequential scraping when possible.
- Don't remove Pydantic null-coercion validators in `extraction/schema.py` or `vision/schema.py` — Gemini returns nulls and they would crash the pipeline.
- Don't run any job over more than ~50 documents without first running it on 5 successfully.

## Firestore collections

| Collection | Purpose |
|---|---|
| `documents` | Every file with all metadata + embedding vectors |
| `events` | Extracted incidents (what/where/when/who/why) |
| `people` | Perpetrators/associates/witnesses (real names) |
| `victims` | Numbered only (no PII) |
| `victim_identity_mapping` | **PRIVATE.** AES-256 encrypted. Server-side only. |
| `locations` | Deduplicated places mentioned in events |
| `properties` | Epstein physical locations grouping exhibits |
| `exhibits` | FBI room placards grouping sequential photos |
| `image_elements` | Notable items (artwork, books, furniture) for filtering |

## Roadmap (updated 2026-04-23)

### Phase 1 — Make the 1.15M docs searchable — DONE (2026-04-29)
1. ~~**Entity extraction**~~ — **DONE (2026-04-24).** 34.1M entities across 1,144,776 docs. 19.6 hours.
2. ~~**Build search index**~~ — **DONE (2026-04-29).** Switched from local BGE-small (384-dim, 0.9 docs/s) to Gemini embedding-001 via Vertex AI (768-dim, 11.3 docs/s). 2,866,071 chunks embedded in 22.8 hours. Cost: ~$42 of $1,000 GenAI credit. DB: 20 GB on internal NVMe.
   - Embedding backend is configurable via `EMBED_BACKEND` env var (`gemini` or `local`)
   - `build_index --reset` drops chunk/vector tables for re-embedding with a different model
   - Vertex AI quota: ~10-12 docs/s sustainable; faster triggers per-minute token quota (429s auto-retry)

### Phase 2 — Build the website
3. **Next.js frontend** — search/browse UI with entity filters, data set selector, document viewer, timeline view. FastAPI backend is ready. Can start in parallel with Phase 1.

### Phase 3 — Enrich with LLM extraction (uses $1,000 GenAI credit)
4. **Selective Gemini extraction** — use search index to identify high-value docs, then run Gemini 2.5 Flash for tags spaCy can't produce: artwork descriptions, flight manifests, shipping labels, relationships between people. Best bang for the $1K credit.
5. **PersonProfile schema** — track individuals via DL info / DOB / addresses across redacted documents.

### Phase 4 — Cross-reference and expand
6. **Process Data Set 2** with cross-photo matcher (find which Data Set 1 room each celebrity photo was taken in).
7. **Process remaining data sets** (3-7, 12) as needed.
8. **Crowdfund** if needed for full LLM extraction on the giant sets.
