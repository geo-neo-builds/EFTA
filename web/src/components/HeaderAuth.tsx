"use client";

import Link from "next/link";
import { useUser } from "@/lib/auth";

export function HeaderAuth() {
  const { user, loading, signOut } = useUser();

  if (loading) return null;

  if (!user) {
    return (
      <Link
        href="/login"
        className="rounded-md bg-zinc-900 px-3 py-1 text-xs font-medium text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
      >
        Sign in
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-zinc-500 dark:text-zinc-400">
        {user.email}
      </span>
      <button
        onClick={signOut}
        className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
      >
        Sign out
      </button>
    </div>
  );
}
