"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  FacetsResponse,
  SearchHit,
  SearchType,
  Stats,
  getFacets,
  getStats,
  search,
} from "@/lib/api";

type EntityFilter = { type: string; value: string } | null;

export default function HomePage() {
  const [query, setQuery] = useState("");
  const [searchType, setSearchType] = useState<SearchType>("hybrid");
  const [entityFilter, setEntityFilter] = useState<EntityFilter>(null);
  const [dataSet, setDataSet] = useState<number | null>(null);

  const [results, setResults] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const [stats, setStats] = useState<Stats | null>(null);
  const [facets, setFacets] = useState<FacetsResponse | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
    getFacets(20).then(setFacets).catch(() => {});
  }, []);

  async function runSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await search({
        q: query,
        type: searchType,
        data_set: dataSet ?? undefined,
        entity_type: entityFilter?.type,
        entity_value: entityFilter?.value,
        limit: 25,
      });
      setResults(res.results);
      setHasSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

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
              disabled={loading || !query.trim()}
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
          {(entityFilter || dataSet !== null) && (
            <div className="flex gap-2 flex-wrap text-xs">
              {dataSet !== null && (
                <ActiveChip
                  label={`Set ${dataSet}`}
                  onClear={() => setDataSet(null)}
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

        <ul className="space-y-3">
          {results.map((hit) => (
            <li
              key={`${hit.chunk_id}-${hit.match}`}
              className="rounded border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 hover:border-zinc-400 dark:hover:border-zinc-600 transition"
            >
              <div className="flex items-baseline justify-between gap-4 mb-1">
                <Link
                  href={`/doc/${hit.doc_id}?page=${hit.page_number}`}
                  className="font-mono text-sm text-zinc-900 dark:text-zinc-100 hover:underline"
                >
                  {hit.doc_id}
                </Link>
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  page {hit.page_number}
                  {" · "}
                  {hit.match}
                  {" · score "}
                  {hit.score.toFixed(3)}
                </span>
              </div>
              <p
                className="text-sm text-zinc-700 dark:text-zinc-300 leading-relaxed"
                dangerouslySetInnerHTML={{ __html: hit.snippet }}
              />
            </li>
          ))}
        </ul>
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
