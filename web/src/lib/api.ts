// Thin client for the EFTA FastAPI service.
// All endpoints are read-only; no auth.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

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

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function getStats() {
  return getJSON<Stats>("/");
}

export async function search(opts: {
  q?: string;
  type?: SearchType;
  data_set?: number;
  entity_type?: string;
  entity_value?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  if (opts.q) params.set("q", opts.q);
  if (opts.type) params.set("type", opts.type);
  if (opts.data_set !== undefined) params.set("data_set", String(opts.data_set));
  if (opts.entity_type) params.set("entity_type", opts.entity_type);
  if (opts.entity_value) params.set("entity_value", opts.entity_value);
  if (opts.limit) params.set("limit", String(opts.limit));
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
