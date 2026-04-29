"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getTimeline, type TimelineEntry } from "@/lib/api";

export default function TimelinePage() {
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [dataSet, setDataSet] = useState<number | undefined>();
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const limit = 100;

  useEffect(() => {
    setLoading(true);
    setEntries([]);
    setOffset(0);
    setHasMore(true);
    getTimeline({ data_set: dataSet, limit, offset: 0 })
      .then((r) => {
        setEntries(r.entries);
        setHasMore(r.entries.length === limit);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [dataSet]);

  const loadMore = async () => {
    const newOffset = offset + limit;
    const r = await getTimeline({ data_set: dataSet, limit, offset: newOffset });
    setEntries((prev) => [...prev, ...r.entries]);
    setOffset(newOffset);
    setHasMore(r.entries.length === limit);
  };

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100">
          Timeline
        </h1>
        <select
          value={dataSet ?? ""}
          onChange={(e) =>
            setDataSet(e.target.value ? Number(e.target.value) : undefined)
          }
          className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        >
          <option value="">All data sets</option>
          {[8, 9, 10, 11].map((ds) => (
            <option key={ds} value={ds}>
              Set {ds}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <p className="text-center text-zinc-400">Loading timeline...</p>
      ) : entries.length === 0 ? (
        <p className="text-center text-zinc-400">No dated entries found.</p>
      ) : (
        <div className="relative border-l-2 border-zinc-200 pl-6 dark:border-zinc-700">
          {entries.map((entry, i) => (
            <div key={`${entry.date}-${i}`} className="relative mb-6">
              {/* Dot */}
              <div className="absolute -left-[31px] top-1 h-3 w-3 rounded-full border-2 border-zinc-400 bg-white dark:border-zinc-500 dark:bg-zinc-900" />

              {/* Date label */}
              <div className="mb-1 text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                {entry.date}
                <span className="ml-2 text-xs font-normal text-zinc-400">
                  ({entry.doc_count} document{entry.doc_count !== 1 ? "s" : ""})
                </span>
              </div>

              {/* Doc links */}
              <div className="flex flex-wrap gap-1.5">
                {entry.doc_ids.map((docId) => (
                  <Link
                    key={docId}
                    href={`/doc/${docId}`}
                    className="inline-block rounded bg-zinc-100 px-2 py-0.5 font-mono text-xs text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-700"
                  >
                    {docId}
                  </Link>
                ))}
                {entry.doc_count > entry.doc_ids.length && (
                  <span className="px-2 py-0.5 text-xs text-zinc-400">
                    +{entry.doc_count - entry.doc_ids.length} more
                  </span>
                )}
              </div>
            </div>
          ))}

          {hasMore && (
            <button
              onClick={loadMore}
              className="ml-2 rounded-md bg-zinc-100 px-4 py-2 text-sm text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
            >
              Load more
            </button>
          )}
        </div>
      )}
    </div>
  );
}
