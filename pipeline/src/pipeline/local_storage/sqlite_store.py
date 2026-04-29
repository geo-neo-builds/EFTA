"""SQLite-based document + search store.

One file holds everything: doc metadata, per-page text, chunks, FTS5
keyword index, and `sqlite-vec` embedding index. Servable directly from a
Cloud Run container with no extra infra.

Uses `apsw` (Another Python SQLite Wrapper) rather than the stdlib
`sqlite3` module because the macOS system / python.org builds of Python
disable `enable_load_extension`, which sqlite-vec requires. APSW bundles
a modern SQLite and supports extensions out of the box.

Schema (all tables use `IF NOT EXISTS` so repeated open is safe):

  documents         one row per source PDF
  pages             one row per page (full text for display)
  chunks            one row per embedding-unit chunk
  chunks_fts        FTS5 virtual table mirroring chunks.text
  chunks_vec        sqlite-vec virtual table storing one vector per chunk
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pipeline.embeddings.chunker import Chunk

logger = logging.getLogger(__name__)


@dataclass
class DocumentRecord:
    doc_id: str           # e.g. "EFTA00009889"
    data_set: int
    filename: str
    source_url: str
    page_count: int
    total_chars: int


def _rows_as_dicts(cursor) -> list[dict]:
    """APSW cursors yield tuples; description must be read before exhaustion."""
    results: list[dict] = []
    cols: list[str] | None = None
    for row in cursor:
        if cols is None:
            cols = [d[0] for d in cursor.getdescription()]
        results.append(dict(zip(cols, row)))
    return results


class SQLiteStore:
    """Handles schema creation, inserts, and search queries."""

    def __init__(self, db_path: Path, embed_dim: int = 768):
        self.db_path = db_path
        self.embed_dim = embed_dim
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None

    def _connect(self):
        try:
            import apsw
        except ImportError as e:
            raise RuntimeError(
                "apsw not installed. Run: pip install apsw"
            ) from e
        try:
            import sqlite_vec
        except ImportError as e:
            raise RuntimeError(
                "sqlite-vec not installed. Run: pip install -e '.[local]'"
            ) from e

        conn = apsw.Connection(str(self.db_path))
        conn.enable_load_extension(True)
        conn.load_extension(sqlite_vec.loadable_path())
        conn.enable_load_extension(False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @property
    def conn(self):
        if self._conn is None:
            self._conn = self._connect()
            self._init_schema(self._conn)
        return self._conn

    def _init_schema(self, conn) -> None:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id       TEXT PRIMARY KEY,
                data_set     INTEGER NOT NULL,
                filename     TEXT NOT NULL,
                source_url   TEXT NOT NULL,
                page_count   INTEGER NOT NULL,
                total_chars  INTEGER NOT NULL,
                created_at   INTEGER DEFAULT (unixepoch())
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                doc_id       TEXT NOT NULL,
                page_number  INTEGER NOT NULL,
                text         TEXT NOT NULL,
                char_count   INTEGER NOT NULL,
                PRIMARY KEY (doc_id, page_number),
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id           TEXT NOT NULL,
                page_number      INTEGER NOT NULL,
                sub_chunk_index  INTEGER NOT NULL,
                text             TEXT NOT NULL,
                char_count       INTEGER NOT NULL,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);")
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(text, content='chunks', content_rowid='chunk_id');
        """)
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec
                USING vec0(embedding FLOAT[{self.embed_dim}]);
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                entity_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id            TEXT NOT NULL,
                page_number       INTEGER NOT NULL,
                entity_type       TEXT NOT NULL,
                value             TEXT NOT NULL,
                normalized_value  TEXT NOT NULL,
                char_start        INTEGER,
                char_end          INTEGER,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_doc ON entities(doc_id);")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type_value "
            "ON entities(entity_type, normalized_value);"
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def reset_chunks(self) -> None:
        """Drop all chunk/vector/FTS data for full re-indexing with a new model."""
        conn = self.conn
        conn.execute("DROP TABLE IF EXISTS chunks_vec")
        conn.execute("DROP TABLE IF EXISTS chunks_fts")
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM documents")
        conn.execute("DELETE FROM pages")
        # Recreate virtual tables
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(text, content='chunks', content_rowid='chunk_id');
        """)
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec
                USING vec0(embedding FLOAT[{self.embed_dim}]);
        """)
        logger.info("Reset chunks/documents/pages/FTS/vec tables (embed_dim=%d)", self.embed_dim)

    # ---- transactions ----

    @contextmanager
    def transaction(self):
        conn = self.conn
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # ---- writes ----

    def upsert_document(self, doc: DocumentRecord, pages: list[tuple[int, str]]) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO documents
                       (doc_id, data_set, filename, source_url, page_count, total_chars)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(doc_id) DO UPDATE SET
                       data_set=excluded.data_set,
                       filename=excluded.filename,
                       source_url=excluded.source_url,
                       page_count=excluded.page_count,
                       total_chars=excluded.total_chars""",
                (doc.doc_id, doc.data_set, doc.filename, doc.source_url,
                 doc.page_count, doc.total_chars),
            )
            conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc.doc_id,))
            conn.executemany(
                "INSERT INTO pages (doc_id, page_number, text, char_count) VALUES (?, ?, ?, ?)",
                [(doc.doc_id, pn, t, len(t)) for pn, t in pages],
            )

    def insert_chunks(
        self,
        chunks: list[Chunk],
        vectors: np.ndarray,
    ) -> list[int]:
        if len(chunks) != vectors.shape[0]:
            raise ValueError(
                f"chunks ({len(chunks)}) and vectors ({vectors.shape[0]}) length mismatch"
            )
        if vectors.shape[1] != self.embed_dim:
            raise ValueError(
                f"expected {self.embed_dim}-dim vectors, got {vectors.shape[1]}"
            )
        vectors = vectors.astype(np.float32)

        chunk_ids: list[int] = []
        with self.transaction() as conn:
            doc_ids = {c.doc_id for c in chunks}
            for did in doc_ids:
                old_cur = conn.execute(
                    "SELECT chunk_id FROM chunks WHERE doc_id = ?", (did,)
                )
                for (cid,) in old_cur:
                    conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (cid,))
                    conn.execute("DELETE FROM chunks_vec WHERE rowid = ?", (cid,))
                conn.execute("DELETE FROM chunks WHERE doc_id = ?", (did,))

            for ch, vec in zip(chunks, vectors):
                conn.execute(
                    """INSERT INTO chunks
                           (doc_id, page_number, sub_chunk_index, text, char_count)
                       VALUES (?, ?, ?, ?, ?)""",
                    (ch.doc_id, ch.page_number, ch.sub_chunk_index, ch.text, ch.char_count),
                )
                cid = conn.last_insert_rowid()
                chunk_ids.append(cid)
                conn.execute(
                    "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)",
                    (cid, ch.text),
                )
                conn.execute(
                    "INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
                    (cid, vec.tobytes()),
                )
        return chunk_ids

    def replace_entities(
        self,
        doc_id: str,
        entities: list[tuple[int, str, str, str, int | None, int | None]],
    ) -> int:
        """Replace all entities for a document. Tuples: (page, type, value, normalized, start, end)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM entities WHERE doc_id = ?", (doc_id,))
            conn.executemany(
                """INSERT INTO entities
                       (doc_id, page_number, entity_type, value, normalized_value, char_start, char_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(doc_id, pn, t, v, n, s, e) for pn, t, v, n, s, e in entities],
            )
        return len(entities)

    # ---- reads / search ----

    def keyword_search(self, query: str, limit: int = 20) -> list[dict]:
        cur = self.conn.execute(
            """SELECT c.chunk_id, c.doc_id, c.page_number, c.sub_chunk_index,
                      snippet(chunks_fts, 0, '<b>', '</b>', '…', 20) AS snippet,
                      bm25(chunks_fts) AS rank
               FROM chunks_fts
               JOIN chunks c ON c.chunk_id = chunks_fts.rowid
               WHERE chunks_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        )
        return _rows_as_dicts(cur)

    def semantic_search(self, query_vec: np.ndarray, limit: int = 20) -> list[dict]:
        q = query_vec.astype(np.float32).tobytes()
        cur = self.conn.execute(
            """SELECT c.chunk_id, c.doc_id, c.page_number, c.sub_chunk_index,
                      c.text, v.distance
               FROM chunks_vec v
               JOIN chunks c ON c.chunk_id = v.rowid
               WHERE v.embedding MATCH ? AND k = ?
               ORDER BY v.distance""",
            (q, limit),
        )
        return _rows_as_dicts(cur)

    def stats(self) -> dict:
        def one(sql):
            return next(iter(self.conn.execute(sql)))[0]
        return {
            "documents": one("SELECT COUNT(*) FROM documents"),
            "pages":     one("SELECT COUNT(*) FROM pages"),
            "chunks":    one("SELECT COUNT(*) FROM chunks"),
            "entities":  one("SELECT COUNT(*) FROM entities"),
        }

    def existing_doc_ids(self, predicate_sql: str) -> set[str]:
        """Return doc_ids matching `SELECT doc_id FROM ... WHERE predicate_sql`.

        Helper for resumable jobs. Example:
            store.existing_doc_ids("SELECT DISTINCT doc_id FROM chunks")
        """
        return {row[0] for row in self.conn.execute(predicate_sql)}
