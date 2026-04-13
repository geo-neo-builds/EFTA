"use client";

import Link from "next/link";
import { useSearchParams, useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  DocumentMeta,
  EntitiesResponse,
  PageText,
  getDocument,
  getDocumentEntities,
  getDocumentPage,
} from "@/lib/api";

export default function DocumentPage() {
  const params = useParams<{ docId: string }>();
  const searchParams = useSearchParams();
  const docId = params.docId;
  const initialPage = Number(searchParams.get("page") ?? 1);

  const [meta, setMeta] = useState<DocumentMeta | null>(null);
  const [entities, setEntities] = useState<EntitiesResponse | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(initialPage);
  const [pageText, setPageText] = useState<PageText | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    getDocument(docId).then(setMeta).catch((e) => setError(String(e)));
    getDocumentEntities(docId).then(setEntities).catch(() => {});
  }, [docId]);

  useEffect(() => {
    setPageText(null);
    if (!meta) return;
    getDocumentPage(docId, currentPage).then(setPageText).catch(() => {});
  }, [docId, currentPage, meta]);

  if (error) {
    return (
      <div className="rounded border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950 p-4 text-sm text-red-700 dark:text-red-300">
        {error}
      </div>
    );
  }

  if (!meta) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-8">
      {/* ---------- page viewer ---------- */}
      <section>
        <header className="mb-4">
          <div className="text-xs text-zinc-500 dark:text-zinc-400 mb-1">
            <Link href="/" className="hover:underline">
              ← all results
            </Link>
            <span className="mx-2">·</span>
            Data Set {meta.data_set}
          </div>
          <h1 className="font-mono text-2xl tracking-tight">{meta.doc_id}</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400 mt-1">
            {meta.filename} · {meta.page_count} pages ·{" "}
            {meta.total_chars.toLocaleString()} chars
          </p>
          <a
            href={meta.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 underline"
          >
            View original PDF on justice.gov
          </a>
        </header>

        <PageNav
          total={meta.page_count}
          current={currentPage}
          onChange={setCurrentPage}
        />

        <article className="mt-4 rounded border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 min-h-[300px]">
          {pageText === null ? (
            <p className="text-sm text-zinc-400 dark:text-zinc-500">loading page…</p>
          ) : pageText.text.trim() === "" ? (
            <p className="text-sm text-zinc-400 dark:text-zinc-500 italic">
              (this page has no extractable text)
            </p>
          ) : (
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-900 dark:text-zinc-100">
              {pageText.text}
            </pre>
          )}
        </article>

        <PageNav
          total={meta.page_count}
          current={currentPage}
          onChange={setCurrentPage}
        />
      </section>

      {/* ---------- entities sidebar ---------- */}
      <aside>
        <h2 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider mb-2">
          Entities in this document
        </h2>
        {!entities ? (
          <p className="text-sm text-zinc-400 dark:text-zinc-500">loading…</p>
        ) : Object.keys(entities.entities_by_type).length === 0 ? (
          <p className="text-sm text-zinc-400 dark:text-zinc-500">No entities extracted yet.</p>
        ) : (
          <div className="space-y-4">
            {Object.entries(entities.entities_by_type).map(([type, list]) => {
              const counts = new Map<string, number>();
              for (const e of list) {
                counts.set(e.value, (counts.get(e.value) ?? 0) + 1);
              }
              const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
              return (
                <section key={type}>
                  <h3 className="text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                    {type}{" "}
                    <span className="text-zinc-400 dark:text-zinc-500 font-normal">
                      ({list.length})
                    </span>
                  </h3>
                  <ul className="space-y-0.5">
                    {sorted.slice(0, 15).map(([value, count]) => (
                      <li
                        key={value}
                        className="flex items-center justify-between text-sm text-zinc-700 dark:text-zinc-300"
                      >
                        <span className="truncate">{value}</span>
                        <span className="ml-2 shrink-0 text-xs text-zinc-400 dark:text-zinc-500">
                          {count}
                        </span>
                      </li>
                    ))}
                    {sorted.length > 15 && (
                      <li className="text-xs text-zinc-400 dark:text-zinc-500 italic">
                        + {sorted.length - 15} more
                      </li>
                    )}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </aside>
    </div>
  );
}

function PageNav({
  total,
  current,
  onChange,
}: {
  total: number;
  current: number;
  onChange: (n: number) => void;
}) {
  return (
    <nav className="flex items-center justify-between text-sm">
      <button
        onClick={() => onChange(Math.max(1, current - 1))}
        disabled={current <= 1}
        className="rounded border border-zinc-300 dark:border-zinc-700 px-3 py-1 bg-white dark:bg-zinc-900 dark:text-zinc-100 disabled:opacity-40"
      >
        ← prev
      </button>
      <span className="text-zinc-600 dark:text-zinc-300">
        Page{" "}
        <input
          type="number"
          min={1}
          max={total}
          value={current}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (n >= 1 && n <= total) onChange(n);
          }}
          className="w-16 text-center border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 dark:text-zinc-100 rounded px-1 py-0.5 mx-1"
        />
        of {total}
      </span>
      <button
        onClick={() => onChange(Math.min(total, current + 1))}
        disabled={current >= total}
        className="rounded border border-zinc-300 dark:border-zinc-700 px-3 py-1 bg-white dark:bg-zinc-900 dark:text-zinc-100 disabled:opacity-40"
      >
        next →
      </button>
    </nav>
  );
}
