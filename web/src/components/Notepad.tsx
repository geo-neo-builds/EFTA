"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  getNotes,
  saveNotes,
  getBookmarks,
  deleteBookmark,
  type Bookmark,
} from "@/lib/api";
import { useUser } from "@/lib/auth";

type Tab = "notes" | "bookmarks";

export default function Notepad() {
  const { user } = useUser();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("notes");
  const [notes, setNotes] = useState("");
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loaded = useRef(false);

  // Load notes + bookmarks on first open
  useEffect(() => {
    if (!user || loaded.current) return;
    loaded.current = true;
    getNotes().then((r) => setNotes(r.content)).catch(() => {});
    getBookmarks().then((r) => setBookmarks(r.bookmarks)).catch(() => {});
  }, [user]);

  // Restore position from localStorage; default to bottom-right
  useEffect(() => {
    const saved = localStorage.getItem("efta-notepad-pos");
    if (saved) {
      try {
        setPos(JSON.parse(saved));
        return;
      } catch {}
    }
    setPos({
      x: window.innerWidth - 72,
      y: window.innerHeight - 72,
    });
  }, []);

  // Save position to localStorage
  useEffect(() => {
    if (pos) localStorage.setItem("efta-notepad-pos", JSON.stringify(pos));
  }, [pos]);

  useEffect(() => {
    localStorage.setItem("efta-notepad-open", String(open));
  }, [open]);

  // Debounced auto-save notes
  const handleNotesChange = useCallback(
    (val: string) => {
      setNotes(val);
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        saveNotes(val).catch(() => {});
      }, 2000);
    },
    [],
  );

  // Drag handlers
  const didDrag = useRef(false);

  const startDrag = (e: React.MouseEvent) => {
    if (!pos) return;
    if ((e.target as HTMLElement).closest("a, textarea, input")) return;
    setDragging(true);
    didDrag.current = false;
    dragOffset.current = {
      x: e.clientX - pos.x,
      y: e.clientY - pos.y,
    };
    e.preventDefault();
  };

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      didDrag.current = true;
      setPos({
        x: Math.max(0, Math.min(e.clientX - dragOffset.current.x, window.innerWidth - 80)),
        y: Math.max(0, Math.min(e.clientY - dragOffset.current.y, window.innerHeight - 80)),
      });
    };
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  const handleDeleteBookmark = async (id: number) => {
    await deleteBookmark(id).catch(() => {});
    setBookmarks((prev) => prev.filter((b) => b.bookmark_id !== id));
  };

  // Refresh bookmarks (called externally via window event)
  useEffect(() => {
    const handler = () => {
      if (user) {
        getBookmarks().then((r) => setBookmarks(r.bookmarks)).catch(() => {});
      }
    };
    window.addEventListener("efta-bookmark-added", handler);
    return () => window.removeEventListener("efta-bookmark-added", handler);
  }, [user]);

  if (!pos) return null;

  if (!open) {
    return (
      <div
        onMouseDown={startDrag}
        onMouseUp={() => {
          if (!didDrag.current) setOpen(true);
        }}
        style={{ left: `${pos.x}px`, top: `${pos.y}px` }}
        className={`fixed z-50 flex h-12 w-12 items-center justify-center rounded-full bg-zinc-900 text-white shadow-lg hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200 ${dragging ? "cursor-grabbing" : "cursor-grab"}`}
        title="Drag to move, click to open notepad"
        role="button"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 pointer-events-none">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M16 13H8" />
          <path d="M16 17H8" />
          <path d="M10 9H8" />
        </svg>
      </div>
    );
  }

  return (
    <div
      style={{ left: `${pos.x}px`, top: `${pos.y}px` }}
      className={`fixed z-50 flex w-80 flex-col rounded-lg border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900 ${dragging ? "select-none" : ""}`}
    >
      {/* Title bar — draggable */}
      <div
        onMouseDown={startDrag}
        className="flex cursor-move items-center justify-between rounded-t-lg border-b border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-800"
      >
        <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-300">
          Research Notepad
        </span>
        <button
          onClick={() => setOpen(false)}
          className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-zinc-200 dark:border-zinc-700">
        {(["notes", "bookmarks"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 px-3 py-1.5 text-xs font-medium capitalize ${
              tab === t
                ? "border-b-2 border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100"
                : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
            }`}
          >
            {t}
            {t === "bookmarks" && bookmarks.length > 0 && (
              <span className="ml-1 text-zinc-400">({bookmarks.length})</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="max-h-80 overflow-y-auto">
        {!user ? (
          <div className="flex flex-col items-center justify-center gap-3 p-6">
            <p className="text-center text-xs text-zinc-500 dark:text-zinc-400">
              Sign in to save your research notes and bookmarks across sessions.
            </p>
            <Link
              href="/login"
              className="rounded-md bg-zinc-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              Sign in
            </Link>
          </div>
        ) : tab === "notes" ? (
          <textarea
            value={notes}
            onChange={(e) => handleNotesChange(e.target.value)}
            placeholder="Jot down your findings..."
            className="h-60 w-full resize-none bg-transparent p-3 text-sm text-zinc-800 placeholder:text-zinc-400 focus:outline-none dark:text-zinc-200 dark:placeholder:text-zinc-500"
          />
        ) : (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {bookmarks.length === 0 ? (
              <p className="p-3 text-center text-xs text-zinc-400">
                No bookmarks yet. Bookmark documents while searching.
              </p>
            ) : (
              bookmarks.map((b) => (
                <div
                  key={b.bookmark_id}
                  className="flex items-center gap-2 px-3 py-2"
                >
                  <Link
                    href={`/doc/${b.doc_id}${b.page_number ? `?page=${b.page_number}` : ""}`}
                    className="min-w-0 flex-1 truncate text-xs font-mono text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-100"
                  >
                    {b.doc_id}
                    {b.page_number ? ` p.${b.page_number}` : ""}
                  </Link>
                  {b.note && (
                    <span className="truncate text-xs text-zinc-400" title={b.note}>
                      {b.note}
                    </span>
                  )}
                  <button
                    onClick={() => handleDeleteBookmark(b.bookmark_id)}
                    className="shrink-0 text-zinc-300 hover:text-red-500 dark:text-zinc-600 dark:hover:text-red-400"
                    title="Remove bookmark"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
