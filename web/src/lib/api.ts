// Thin client for the EFTA FastAPI service.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type SearchType = "keyword" | "semantic" | "hybrid";

export type SearchHit = {
  chunk_id: number;
  doc_id: string;
  page_number: number;
  sub_chunk_index: number;
  snippet: string;
  score: number;
  match: "keyword" | "semantic" | "filter";
};

export type SearchResponse = {
  query: string;
  type: SearchType;
  results: SearchHit[];
};

export type DocumentMeta = {
  doc_id: string;
  data_set: number;
  filename: string;
  source_url: string;
  page_count: number;
  total_chars: number;
  created_at: number;
  pages: { page_number: number; char_count: number }[];
};

export type PageText = {
  doc_id: string;
  page_number: number;
  char_count: number;
  text: string;
};

export type EntitiesResponse = {
  doc_id: string;
  entities_by_type: Record<
    string,
    { value: string; normalized_value: string; page_number: number }[]
  >;
};

export type FacetsResponse = {
  data_sets: number[];
  doc_types: string[];
  entity_types: string[];
  top_by_type: Record<string, { value: string; doc_count: number }[]>;
};

export type Stats = {
  status: string;
  stats: {
    documents: number;
    pages: number;
    chunks: number;
    entities: number;
  };
};

export type SimilarHit = {
  chunk_id: number;
  doc_id: string;
  page_number: number;
  sub_chunk_index: number;
  preview: string;
  distance: number;
};

export type SimilarResponse = {
  chunk_id: number;
  results: SimilarHit[];
};

export type TimelineEntry = {
  date: string;
  doc_count: number;
  doc_ids: string[];
};

export type TimelineResponse = {
  entries: TimelineEntry[];
  limit: number;
  offset: number;
};

export type User = {
  user_id: number;
  email: string;
  display_name: string | null;
};

export type Bookmark = {
  bookmark_id: number;
  doc_id: string;
  page_number: number | null;
  note: string;
  created_at: number;
};

// ---- fetch helpers ----

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function deleteJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

// ---- public endpoints ----

export async function getStats() {
  return getJSON<Stats>("/");
}

export async function search(opts: {
  q?: string;
  type?: SearchType;
  data_set?: number;
  doc_type?: string;
  entity_type?: string;
  entity_value?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}) {
  const params = new URLSearchParams();
  if (opts.q) params.set("q", opts.q);
  if (opts.type) params.set("type", opts.type);
  if (opts.data_set !== undefined) params.set("data_set", String(opts.data_set));
  if (opts.doc_type) params.set("doc_type", opts.doc_type);
  if (opts.entity_type) params.set("entity_type", opts.entity_type);
  if (opts.entity_value) params.set("entity_value", opts.entity_value);
  if (opts.date_from) params.set("date_from", opts.date_from);
  if (opts.date_to) params.set("date_to", opts.date_to);
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.offset) params.set("offset", String(opts.offset));
  return getJSON<SearchResponse>(`/search?${params.toString()}`);
}

export async function getDocument(docId: string) {
  return getJSON<DocumentMeta>(`/doc/${encodeURIComponent(docId)}`);
}

export async function getDocumentPage(docId: string, pageNumber: number) {
  return getJSON<PageText>(
    `/doc/${encodeURIComponent(docId)}/page/${pageNumber}`,
  );
}

export async function getDocumentEntities(docId: string) {
  return getJSON<EntitiesResponse>(
    `/doc/${encodeURIComponent(docId)}/entities`,
  );
}

export async function getFacets(topN = 25) {
  return getJSON<FacetsResponse>(`/facets?top_n=${topN}`);
}

export async function getSimilar(chunkId: number, limit = 10) {
  return getJSON<SimilarResponse>(`/similar/${chunkId}?limit=${limit}`);
}

export async function getTimeline(opts?: {
  data_set?: number;
  limit?: number;
  offset?: number;
}) {
  const params = new URLSearchParams();
  if (opts?.data_set !== undefined) params.set("data_set", String(opts.data_set));
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  return getJSON<TimelineResponse>(`/timeline?${params.toString()}`);
}

// ---- auth ----

export async function sendMagicLink(email: string) {
  return postJSON<{ ok: boolean }>("/auth/magic-link", { email });
}

export async function verifyMagicLink(token: string) {
  return getJSON<{ ok: boolean; user: User }>(`/auth/verify?token=${token}`);
}

export async function getMe() {
  return getJSON<{ user: User }>("/auth/me");
}

export async function logout() {
  return postJSON<{ ok: boolean }>("/auth/logout");
}

// ---- notes / bookmarks ----

export async function getNotes() {
  return getJSON<{ content: string }>("/notes");
}

export async function saveNotes(content: string) {
  return putJSON<{ ok: boolean }>("/notes", { content });
}

export async function getBookmarks() {
  return getJSON<{ bookmarks: Bookmark[] }>("/bookmarks");
}

export async function addBookmark(docId: string, pageNumber?: number, note?: string) {
  return postJSON<{ ok: boolean; bookmark_id: number }>("/bookmarks", {
    doc_id: docId,
    page_number: pageNumber ?? null,
    note: note ?? "",
  });
}

export async function deleteBookmark(bookmarkId: number) {
  return deleteJSON<{ ok: boolean }>(`/bookmarks/${bookmarkId}`);
}
