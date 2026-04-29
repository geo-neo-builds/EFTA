"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  FacetsResponse,
  SearchHit,
  SearchType,
  SimilarHit,
  Stats,
  addBookmark,
  getFacets,
  getSimilar,
  getStats,
  search,
} from "@/lib/api";
import { useUser } from "@/lib/auth";

type EntityFilter = { type: string; value: string } | null;

import { Suspense } from "react";

export default function HomePage() {
  return (
    <Suspense fallback={<p className="text-zinc-400">Loading...</p>}>
      <HomeContent />
    </Suspense>
  );
}

function HomeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initDone = useRef(false);

  // Initialize state from URL params
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [searchType, setSearchType] = useState<SearchType>(
    (searchParams.get("type") as SearchType) || "hybrid",
  );
  const [entityFilter, setEntityFilter] = useState<EntityFilter>(() => {
    const et = searchParams.get("entity_type");
    const ev = searchParams.get("entity_value");
    return et && ev ? { type: et, value: ev } : null;
  });
  const [dataSet, setDataSet] = useState<number | null>(() => {
    const ds = searchParams.get("data_set");
    return ds ? Number(ds) : null;
  });
  const [docType, setDocType] = useState<string | null>(
    searchParams.get("doc_type"),
  );
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") ?? "");
  const [dateTo, setDateTo] = useState(searchParams.get("date_to") ?? "");

  const [results, setResults] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const PAGE_SIZE = 25;

  const [stats, setStats] = useState<Stats | null>(null);
  const [facets, setFacets] = useState<FacetsResponse | null>(null);
  const [similarMode, setSimilarMode] = useState<{ chunkId: number; hits: SimilarHit[] } | null>(null);
  const { user } = useUser();

  // Sync state → URL (without triggering navigation/reload)
  const syncUrl = useCallback(
    (q: string, st: SearchType, ef: EntityFilter, ds: number | null,
     dt: string | null, df: string, dTo: string) => {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (st !== "hybrid") params.set("type", st);
      if (ef) {
        params.set("entity_type", ef.type);
        params.set("entity_value", ef.value);
      }
      if (ds !== null) params.set("data_set", String(ds));
      if (dt) params.set("doc_type", dt);
      if (df) params.set("date_from", df);
      if (dTo) params.set("date_to", dTo);
      const qs = params.toString();
      router.replace(qs ? `/?${qs}` : "/", { scroll: false });
    },
    [router],
  );

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
    getFacets(20).then(setFacets).catch(() => {});
  }, []);

  const doSearch = useCallback(
    async (q: string, st: SearchType, ef: EntityFilter, ds: number | null,
           dt: string | null, df: string, dTo: string) => {
      const hasFilter = ef !== null || ds !== null || dt !== null || !!df || !!dTo;
      if (!q.trim() && !hasFilter) return;
      setLoading(true);
      setError(null);
      try {
        const res = await search({
          q: q.trim() || undefined,
          type: st,
          data_set: ds ?? undefined,
          doc_type: dt ?? undefined,
          entity_type: ef?.type,
          entity_value: ef?.value,
          date_from: df || undefined,
          date_to: dTo || undefined,
          limit: PAGE_SIZE,
        });
        setResults(res.results);
        setHasSearched(true);
        setHasMore(res.results.length === PAGE_SIZE);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // On initial load: if URL has search params, auto-run the search
  useEffect(() => {
    if (initDone.current) return;
    initDone.current = true;
    const hasFilter = entityFilter !== null || dataSet !== null || docType !== null || !!dateFrom || !!dateTo;
    if (query.trim() || hasFilter) {
      doSearch(query, searchType, entityFilter, dataSet, docType, dateFrom, dateTo);
    }
  }, [query, searchType, entityFilter, dataSet, docType, dateFrom, dateTo, doSearch]);

  function runSearch(e?: React.FormEvent) {
    e?.preventDefault();
    syncUrl(query, searchType, entityFilter, dataSet, docType, dateFrom, dateTo);
    doSearch(query, searchType, entityFilter, dataSet, docType, dateFrom, dateTo);
  }

  async function loadMore() {
    setLoadingMore(true);
    try {
      const res = await search({
        q: query.trim() || undefined,
        type: searchType,
        data_set: dataSet ?? undefined,
        doc_type: docType ?? undefined,
        entity_type: entityFilter?.type,
        entity_value: entityFilter?.value,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: PAGE_SIZE,
        offset: results.length,
      });
      setResults((prev) => [...prev, ...res.results]);
      setHasMore(res.results.length === PAGE_SIZE);
    } catch {
    } finally {
      setLoadingMore(false);
    }
  }

  // Auto-fire when a filter is toggled
  useEffect(() => {
    if (!initDone.current) return;
    const hasFilter = entityFilter !== null || dataSet !== null || docType !== null || !!dateFrom || !!dateTo;
    if (!hasFilter && !hasSearched) return;
    if (!hasFilter && !query.trim()) {
      setResults([]);
      setHasSearched(false);
      syncUrl("", searchType, null, null, null, "", "");
      return;
    }
    syncUrl(query, searchType, entityFilter, dataSet, docType, dateFrom, dateTo);
    doSearch(query, searchType, entityFilter, dataSet, docType, dateFrom, dateTo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityFilter, dataSet, docType, dateFrom, dateTo]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-8">
      {/* ---------- filters ---------- */}
      <aside className="space-y-6">
        <section>
          <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">
            Corpus
          </h2>
          {stats ? (
            <ul className="text-sm text-zinc-700 dark:text-zinc-300 space-y-0.5">
              <li>{stats.stats.documents.toLocaleString()} documents</li>
              <li>{stats.stats.pages.toLocaleString()} pages</li>
              <li>{stats.stats.chunks.toLocaleString()} chunks</li>
              <li>{stats.stats.entities.toLocaleString()} entities</li>
            </ul>
          ) : (
            <p className="text-sm text-zinc-400 dark:text-zinc-500">loading…</p>
          )}
        </section>

        {/* Doc type filter */}
        {facets?.doc_types && facets.doc_types.length > 0 && (
          <FilterSection
            title="Document type"
            clearLabel={docType ? "clear" : undefined}
            onClear={() => setDocType(null)}
          >
            {facets.doc_types.map((dt) => (
              <button
                key={dt}
                onClick={() => setDocType(docType === dt ? null : dt)}
                className={`block w-full text-left text-sm px-2 py-1 rounded capitalize ${
                  docType === dt
                    ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300"
                }`}
              >
                {dt.replace(/_/g, " ")}
              </button>
            ))}
          </FilterSection>
        )}

        {/* Date range filter */}
        <FilterSection
          title="Date range"
          clearLabel={dateFrom || dateTo ? "clear" : undefined}
          onClear={() => { setDateFrom(""); setDateTo(""); }}
        >
          <div className="space-y-1.5">
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="block w-full rounded border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1 text-xs text-zinc-700 dark:text-zinc-300"
              placeholder="From"
            />
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="block w-full rounded border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1 text-xs text-zinc-700 dark:text-zinc-300"
              placeholder="To"
            />
          </div>
        </FilterSection>

        <FilterSection
          title="Data set"
          clearLabel={dataSet !== null ? "clear" : undefined}
          onClear={() => setDataSet(null)}
        >
          {facets?.data_sets.map((ds) => (
            <button
              key={ds}
              onClick={() => setDataSet(dataSet === ds ? null : ds)}
              className={`block w-full text-left text-sm px-2 py-1 rounded ${
                dataSet === ds
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300"
              }`}
            >
              Set {ds}
            </button>
          ))}
        </FilterSection>

        {facets &&
          Object.entries(facets.top_by_type).map(([type, values]) =>
            values.length === 0 ? null : (
              <FilterSection
                key={type}
                title={type}
                clearLabel={
                  entityFilter?.type === type ? "clear" : undefined
                }
                onClear={() => setEntityFilter(null)}
              >
                {values.slice(0, 10).map((v) => {
                  const selected =
                    entityFilter?.type === type &&
                    entityFilter?.value === v.value;
                  return (
                    <button
                      key={v.value}
                      onClick={() =>
                        setEntityFilter(
                          selected ? null : { type, value: v.value },
                        )
                      }
                      className={`flex w-full items-center justify-between text-sm px-2 py-1 rounded ${
                        selected
                          ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                          : "hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300"
                      }`}
                    >
                      <span className="truncate">{v.value}</span>
                      <span className="ml-2 shrink-0 text-xs opacity-70">
                        {v.doc_count}
                      </span>
                    </button>
                  );
                })}
              </FilterSection>
            ),
          )}
      </aside>

      {/* ---------- search + results ---------- */}
      <section>
        <form onSubmit={runSearch} className="flex flex-col gap-3 mb-6">
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search across documents…"
              className="flex-1 rounded border border-zinc-300 dark:border-zinc-700 px-4 py-2 bg-white dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-600"
            />
            <button
              type="submit"
              disabled={
                loading ||
                (!query.trim() && entityFilter === null && dataSet === null)
              }
              className="rounded bg-zinc-900 dark:bg-zinc-100 dark:text-zinc-900 px-4 py-2 text-white text-sm disabled:opacity-50"
            >
              {loading ? "…" : "Search"}
            </button>
          </div>
          <div className="flex items-center gap-4 text-sm">
            {(["hybrid", "keyword", "semantic"] as SearchType[]).map((t) => (
              <label key={t} className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="searchtype"
                  checked={searchType === t}
                  onChange={() => setSearchType(t)}
                />
                <span className="capitalize">{t}</span>
              </label>
            ))}
          </div>
          {(entityFilter || dataSet !== null || docType || dateFrom || dateTo) && (
            <div className="flex gap-2 flex-wrap text-xs">
              {dataSet !== null && (
                <ActiveChip
                  label={`Set ${dataSet}`}
                  onClear={() => setDataSet(null)}
                />
              )}
              {docType && (
                <ActiveChip
                  label={`Type: ${docType.replace(/_/g, " ")}`}
                  onClear={() => setDocType(null)}
                />
              )}
              {(dateFrom || dateTo) && (
                <ActiveChip
                  label={`Date: ${dateFrom || "..."} – ${dateTo || "..."}`}
                  onClear={() => { setDateFrom(""); setDateTo(""); }}
                />
              )}
              {entityFilter && (
                <ActiveChip
                  label={`${entityFilter.type}: ${entityFilter.value}`}
                  onClear={() => setEntityFilter(null)}
                />
              )}
            </div>
          )}
        </form>

        {error && (
          <div className="mb-4 rounded border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950 p-3 text-sm text-red-700 dark:text-red-300">
            {error}
          </div>
        )}

        {!hasSearched && !loading && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Type a query above. Use filters on the left to narrow by entity or data set.
          </p>
        )}

        {hasSearched && results.length === 0 && !loading && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No results.</p>
        )}

        {similarMode && (
          <div className="mb-4">
            <button
              onClick={() => setSimilarMode(null)}
              className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
            >
              &larr; Back to search results
            </button>
            <h3 className="mt-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              Documents similar to chunk #{similarMode.chunkId}
            </h3>
          </div>
        )}

        <ul className="space-y-3">
          {(similarMode
            ? similarMode.hits.map((h) => ({
                chunk_id: h.chunk_id,
                doc_id: h.doc_id,
                page_number: h.page_number,
                sub_chunk_index: h.sub_chunk_index,
                snippet: h.preview,
                score: h.distance,
                match: "semantic" as const,
              }))
            : results
          ).map((hit) => {
            const hl =
              query.trim() || entityFilter?.value || "";
            const href =
              `/doc/${encodeURIComponent(hit.doc_id)}` +
              `?page=${hit.page_number}` +
              (hl ? `&hl=${encodeURIComponent(hl)}` : "");
            return (
              <li key={`${hit.chunk_id}-${hit.match}`}>
                <Link
                  href={href}
                  className="block rounded border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 hover:bg-zinc-50 dark:hover:bg-zinc-800/60 transition"
                >
                  <div className="flex items-baseline justify-between gap-4 mb-1">
                    <span className="font-mono text-sm text-zinc-900 dark:text-zinc-100">
                      {hit.doc_id}
                    </span>
                    <span className="text-xs text-zinc-500 dark:text-zinc-400">
                      page {hit.page_number}
                      {" · "}
                      {hit.match}
                      {hit.match !== "filter" &&
                        ` · score ${hit.score.toFixed(3)}`}
                    </span>
                  </div>
                  <p
                    className="text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: hit.snippet }}
                  />
                </Link>
                <div className="mt-1.5 flex gap-2">
                  <button
                    onClick={async (e) => {
                      e.preventDefault();
                      const res = await getSimilar(hit.chunk_id, 10);
                      setSimilarMode({ chunkId: hit.chunk_id, hits: res.results });
                    }}
                    className="text-xs text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
                  >
                    Similar
                  </button>
                  {user && (
                    <button
                      onClick={async (e) => {
                        e.preventDefault();
                        await addBookmark(hit.doc_id, hit.page_number);
                        window.dispatchEvent(new Event("efta-bookmark-added"));
                      }}
                      className="text-xs text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
                    >
                      Bookmark
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>

        {hasMore && !similarMode && (
          <div className="mt-4 text-center">
            <button
              onClick={loadMore}
              disabled={loadingMore}
              className="rounded bg-zinc-100 px-6 py-2 text-sm text-zinc-700 hover:bg-zinc-200 disabled:opacity-50 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
            >
              {loadingMore ? "Loading..." : "Load more results"}
            </button>
          </div>
        )}

        {hasSearched && results.length > 0 && (
          <p className="mt-3 text-center text-xs text-zinc-400">
            Showing {results.length} result{results.length !== 1 ? "s" : ""}
          </p>
        )}
      </section>
    </div>
  );
}

function FilterSection({
  title,
  children,
  clearLabel,
  onClear,
}: {
  title: string;
  children: React.ReactNode;
  clearLabel?: string;
  onClear?: () => void;
}) {
  return (
    <section>
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
          {title}
        </h2>
        {clearLabel && (
          <button
            onClick={onClear}
            className="text-xs text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
          >
            {clearLabel}
          </button>
        )}
      </div>
      <div className="space-y-0.5">{children}</div>
    </section>
  );
}

function ActiveChip({
  label,
  onClear,
}: {
  label: string;
  onClear: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 px-2 py-0.5">
      {label}
      <button onClick={onClear} className="hover:opacity-80" aria-label="clear filter">
        ×
      </button>
    </span>
  );
}
