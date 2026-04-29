"""Search + browse API for the EFTA local pipeline.

Endpoints:
  GET  /                     health + DB stats
  GET  /search               keyword | semantic | hybrid search with filters
  GET  /doc/{doc_id}         document metadata + page list
  GET  /doc/{doc_id}/page/{page_number}
                             full text of a specific page
  GET  /doc/{doc_id}/entities
                             all entities in a doc, grouped by type
  GET  /similar/{chunk_id}   most similar chunks to a given chunk
  GET  /facets               available filter values for the UI

Response shape is JSON throughout.

Run locally:
    uvicorn pipeline.api.app:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from pipeline.config import config
from pipeline.embeddings import get_embedder
from pipeline.local_storage.paths import load_paths
from pipeline.local_storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# Module-level singletons; populated in the lifespan handler so tests can
# patch them if needed.
_store: SQLiteStore | None = None
_embedder = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store, _embedder
    paths = load_paths()
    _store = SQLiteStore(paths.db_file, embed_dim=config.embed_dim)
    _embedder = get_embedder()
    logger.info("API ready. DB=%s, embedder=%s", paths.db_file, config.embed_backend)
    yield
    if _store is not None:
        _store.close()


app = FastAPI(
    title="EFTA Search API",
    description="Local-only, zero-cost search over DOJ Epstein disclosures.",
    lifespan=lifespan,
)

# Allow the Next.js frontend to call this from another origin in dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _store_or_500() -> SQLiteStore:
    if _store is None:
        raise HTTPException(500, "Store not initialized")
    return _store


def _embed_query(text: str) -> np.ndarray:
    if _embedder is None:
        raise HTTPException(500, "Embedder not initialized")
    return _embedder.embed([text]).vectors[0]


def _browse_by_filter(
    store: SQLiteStore,
    entity_type: str | None,
    entity_value: str | None,
    doc_filter: set[str] | None,
    limit: int,
) -> list[dict]:
    """Filter-only listing used when the user selects a facet with no query.

    If an entity filter is active we surface the chunks that sit on pages
    where that entity appears (so users see the passage their filter
    matched). Otherwise we return the first chunk of each doc in scope.
    """
    if entity_type and entity_value:
        cur = store.conn.execute(
            """SELECT c.chunk_id, c.doc_id, c.page_number, c.sub_chunk_index,
                      substr(c.text, 1, 240) AS snippet
               FROM entities e
               JOIN chunks c ON c.doc_id = e.doc_id AND c.page_number = e.page_number
               WHERE e.entity_type = ? AND e.normalized_value = ?
               GROUP BY c.chunk_id
               ORDER BY c.doc_id, c.page_number, c.sub_chunk_index
               LIMIT ?""",
            (entity_type, entity_value.lower(), limit),
        )
    else:
        # data_set-only browse: first chunk per doc in scope.
        placeholders = ",".join("?" * len(doc_filter or []))
        cur = store.conn.execute(
            f"""SELECT chunk_id, doc_id, page_number, sub_chunk_index,
                       substr(text, 1, 240) AS snippet
                FROM chunks
                WHERE doc_id IN ({placeholders})
                  AND sub_chunk_index = 0
                GROUP BY doc_id
                ORDER BY doc_id
                LIMIT ?""",
            (*(doc_filter or []), limit),
        )

    results = []
    cols = None
    for row in cur:
        if cols is None:
            cols = [d[0] for d in cur.getdescription()]
        d = dict(zip(cols, row))
        d["score"] = 0.0
        d["match"] = "filter"
        results.append(d)
    return results


# ---------- endpoints ----------


@app.get("/")
def root():
    store = _store_or_500()
    return {
        "status": "ok",
        "stats": store.stats(),
    }


@app.get("/search")
def search(
    q: str | None = Query(None, description="query text; optional if a filter is set"),
    type: Literal["keyword", "semantic", "hybrid"] = "hybrid",
    data_set: int | None = None,
    entity_type: str | None = Query(None, description="e.g. PERSON, GPE, ORG"),
    entity_value: str | None = Query(None, description="normalized entity value"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search chunks by keyword (FTS5), meaning (vectors), or both.

    `entity_type`+`entity_value` together restrict results to docs that
    contain that specific entity (e.g. type=GPE, value="new york").
    `data_set` restricts to a specific data set number.

    If `q` is empty but a filter is set, returns a browse-mode listing
    of the chunks on pages where that filter matches, so users can
    explore "all docs mentioning X" without typing a query.
    """
    store = _store_or_500()
    has_q = bool(q and q.strip())
    has_filter = bool((entity_type and entity_value) or data_set is not None)
    if not has_q and not has_filter:
        raise HTTPException(
            400, "Provide a query (q) or a filter (data_set / entity_type+entity_value)."
        )

    # Build an optional doc_id restriction from the entity + data_set filters.
    doc_filter: set[str] | None = None
    if entity_type and entity_value:
        rows = store.conn.execute(
            """SELECT DISTINCT doc_id FROM entities
               WHERE entity_type = ? AND normalized_value = ?""",
            (entity_type, entity_value.lower()),
        )
        doc_filter = {r[0] for r in rows}
        if not doc_filter:
            return {"query": q or "", "type": type, "results": []}

    if data_set is not None:
        rows = store.conn.execute(
            "SELECT doc_id FROM documents WHERE data_set = ?", (data_set,)
        )
        ds_ids = {r[0] for r in rows}
        doc_filter = ds_ids if doc_filter is None else (doc_filter & ds_ids)
        if not doc_filter:
            return {"query": q or "", "type": type, "results": []}

    # Filter-only browse mode: no query, just list chunks matching the filter.
    if not has_q:
        return {
            "query": "",
            "type": "filter",
            "results": _browse_by_filter(
                store, entity_type, entity_value, doc_filter, limit,
            ),
        }

    results: list[dict] = []

    # Fetch a generous pool then filter by doc_filter and trim to limit.
    pool = limit * 5 if doc_filter else limit

    if type in ("keyword", "hybrid"):
        for row in store.keyword_search(q, limit=pool):
            if doc_filter and row["doc_id"] not in doc_filter:
                continue
            results.append({
                "chunk_id": row["chunk_id"],
                "doc_id": row["doc_id"],
                "page_number": row["page_number"],
                "sub_chunk_index": row["sub_chunk_index"],
                "snippet": row["snippet"],
                "score": float(row["rank"]),
                "match": "keyword",
            })

    if type in ("semantic", "hybrid"):
        qvec = _embed_query(q)
        for row in store.semantic_search(qvec, limit=pool):
            if doc_filter and row["doc_id"] not in doc_filter:
                continue
            preview = row["text"][:240]
            results.append({
                "chunk_id": row["chunk_id"],
                "doc_id": row["doc_id"],
                "page_number": row["page_number"],
                "sub_chunk_index": row["sub_chunk_index"],
                "snippet": preview,
                "score": float(row["distance"]),
                "match": "semantic",
            })

    # Dedupe by chunk_id keeping the first (lower score for keyword, lower
    # distance for semantic — both "first" means "best").
    seen = set()
    deduped = []
    for r in results:
        if r["chunk_id"] in seen:
            continue
        seen.add(r["chunk_id"])
        deduped.append(r)

    return {"query": q, "type": type, "results": deduped[:limit]}


@app.get("/doc/{doc_id}")
def get_doc(doc_id: str):
    store = _store_or_500()
    doc_row = next(iter(store.conn.execute(
        """SELECT doc_id, data_set, filename, source_url,
                  page_count, total_chars, created_at
           FROM documents WHERE doc_id = ?""",
        (doc_id,),
    )), None)
    if doc_row is None:
        raise HTTPException(404, f"doc {doc_id} not found")

    page_rows = list(store.conn.execute(
        "SELECT page_number, char_count FROM pages WHERE doc_id = ? ORDER BY page_number",
        (doc_id,),
    ))

    return {
        "doc_id": doc_row[0],
        "data_set": doc_row[1],
        "filename": doc_row[2],
        "source_url": doc_row[3],
        "page_count": doc_row[4],
        "total_chars": doc_row[5],
        "created_at": doc_row[6],
        "pages": [{"page_number": p[0], "char_count": p[1]} for p in page_rows],
    }


@app.get("/doc/{doc_id}/page/{page_number}")
def get_page(doc_id: str, page_number: int):
    store = _store_or_500()
    row = next(iter(store.conn.execute(
        "SELECT text, char_count FROM pages WHERE doc_id = ? AND page_number = ?",
        (doc_id, page_number),
    )), None)
    if row is None:
        raise HTTPException(404, f"page {doc_id} p.{page_number} not found")
    return {
        "doc_id": doc_id,
        "page_number": page_number,
        "char_count": row[1],
        "text": row[0],
    }


@app.get("/doc/{doc_id}/entities")
def get_doc_entities(doc_id: str):
    store = _store_or_500()
    rows = store.conn.execute(
        """SELECT entity_type, value, normalized_value, page_number
           FROM entities WHERE doc_id = ?
           ORDER BY entity_type, normalized_value""",
        (doc_id,),
    )
    grouped: dict[str, list[dict]] = {}
    for et, value, norm, page in rows:
        grouped.setdefault(et, []).append({
            "value": value,
            "normalized_value": norm,
            "page_number": page,
        })
    return {"doc_id": doc_id, "entities_by_type": grouped}


@app.get("/similar/{chunk_id}")
def similar_chunks(chunk_id: int, limit: int = Query(10, ge=1, le=50)):
    """Return chunks semantically closest to the given chunk."""
    store = _store_or_500()
    row = next(iter(store.conn.execute(
        "SELECT embedding FROM chunks_vec WHERE rowid = ?", (chunk_id,),
    )), None)
    if row is None:
        raise HTTPException(404, f"chunk {chunk_id} not found")
    vec = np.frombuffer(row[0], dtype=np.float32)
    cur = store.conn.execute(
        """SELECT c.chunk_id, c.doc_id, c.page_number, c.sub_chunk_index,
                  c.text, v.distance
           FROM chunks_vec v
           JOIN chunks c ON c.chunk_id = v.rowid
           WHERE v.embedding MATCH ? AND k = ?
           ORDER BY v.distance""",
        (vec.tobytes(), limit + 1),
    )
    results = []
    cols = None
    for r in cur:
        if cols is None:
            cols = [d[0] for d in cur.getdescription()]
        d = dict(zip(cols, r))
        if d["chunk_id"] == chunk_id:
            continue  # skip self
        d["preview"] = d["text"][:240]
        d["distance"] = float(d["distance"])
        del d["text"]
        results.append(d)
    return {"chunk_id": chunk_id, "results": results[:limit]}


@app.get("/facets")
def facets(top_n: int = Query(25, ge=1, le=200)):
    """Return top filter values per entity type for UI faceting."""
    store = _store_or_500()
    c = store.conn

    data_sets = [r[0] for r in c.execute(
        "SELECT DISTINCT data_set FROM documents ORDER BY data_set"
    )]
    entity_types = [r[0] for r in c.execute(
        "SELECT DISTINCT entity_type FROM entities ORDER BY entity_type"
    )]
    top_by_type: dict[str, list[dict]] = {}
    for et in entity_types:
        rows = c.execute(
            """SELECT normalized_value, COUNT(DISTINCT doc_id) AS doc_count
               FROM entities WHERE entity_type = ?
               GROUP BY normalized_value
               ORDER BY doc_count DESC, normalized_value ASC
               LIMIT ?""",
            (et, top_n),
        )
        top_by_type[et] = [
            {"value": r[0], "doc_count": r[1]} for r in rows
        ]

    return {
        "data_sets": data_sets,
        "entity_types": entity_types,
        "top_by_type": top_by_type,
    }
