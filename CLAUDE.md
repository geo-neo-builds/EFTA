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
- **Cost so far:** $18.43 of $300 GCP credit.

### Survey results
- **Set 2** (~588 files): celebrity photos — Bill Clinton + Epstein together found in samples
- **Set 3** (~98 files): multi-page evidence + 98-page photo album with section labels (ZORRO/VEGAS, LSJ AERIALS, CLOUDS, PRAGUE, PAINTING)
- **Set 4** (~196): Palm Beach Police records (2006 fax logs)
- **Sets 5-7** (small): photos + a few long text docs
- **Sets 8-11** (~1.1 million files combined): native text PDFs — **100% pypdf success**, can extract text for FREE
- **Set 12** (~200): DOJ legal memos including Maxwell prosecution memo

### Not yet built
- The website (Next.js frontend) — API is ready for it
- Cross-photo matcher (find which room a celebrity photo was taken in)
- **Full** Set 8-11 bulk ingest (scaffolding is done; waiting on Akamai IP cooldown before the long overnight URL crawl — listing pages are rate-limited, file URLs are not)
- LLM extraction on Sets 8-11 (deferred — too expensive without funding)
- PersonProfile / Receipt / PhoneMessage / MediaItem schemas

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
- **Time Capsule** (`EFTA_TIME_CAPSULE_ROOT` env var, unset by default) — future
  mirror for raw PDFs. Currently we extract text and discard the PDF; the DOJ
  URL is preserved in the JSON so originals can be re-fetched.
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
| `python -m pipeline.jobs.local_ingest 8 --workers 6` | Crawl DOJ listing pages for Set 8, then parallel-download + pypdf-extract → text JSON on SSD. Resumable. |
| `python -m pipeline.jobs.local_ingest 8 --limit 20` | Same, but cap processed docs (use for tests). |
| `python -m pipeline.jobs.build_index 8` | Read text JSONs for Set 8, chunk + embed locally, write chunks + vectors to SQLite. Resumable. |
| `python -m pipeline.jobs.extract_entities 8` | spaCy + regex NER over text JSONs; write entity rows to SQLite. Resumable. |
| `python -m pipeline.jobs.build_index all` | Any of the above accept `all` to iterate every `set-*` dir. |
| `python -m pipeline.jobs.test_local_pipeline 8 5` | End-to-end smoke test on a 5-doc sample (downloads, does NOT use on-SSD archive). |

### Running the search API
```bash
cd ~/EFTA/pipeline
uvicorn pipeline.api.app:app --reload --port 8000
```
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

### Current DB state (as of last validation)
```
documents: 20   pages: 153   chunks: 206   entities: 2,250  (Set 8 sample only)
```

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

## Future plans (when budget allows)

1. **Build the website** (Next.js) — filter UI, floating notepad widget, user accounts, tabs, timeline view, cross-document matching
2. **Process Data Set 2** with cross-photo matcher (find which Data Set 1 room each celebrity photo was taken in)
3. **Free text extraction on Sets 8-11** ($0)
4. **Selective LLM extraction** on text docs — embed first, then only extract from relevant ones
5. **Crowdfund** if needed to do full LLM extraction on the giant sets
6. **PersonProfile schema** for tracking individuals via DL info / DOB / addresses across redacted documents
