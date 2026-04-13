"use client";

import { useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";

const STORAGE_KEY = "efta-theme";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  const dark =
    theme === "dark" ||
    (theme === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", dark);
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const stored = (localStorage.getItem(STORAGE_KEY) as Theme) || "system";
    setTheme(stored);
    setMounted(true);

    // Keep in sync with OS changes when the user is on "system"
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const t = (localStorage.getItem(STORAGE_KEY) as Theme) || "system";
      if (t === "system") applyTheme("system");
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  function choose(t: Theme) {
    setTheme(t);
    localStorage.setItem(STORAGE_KEY, t);
    applyTheme(t);
  }

  // Avoid hydration mismatch: render a stable placeholder on the server.
  if (!mounted) {
    return <div className="h-7 w-[116px]" aria-hidden />;
  }

  return (
    <div
      className="inline-flex rounded border border-zinc-300 dark:border-zinc-700 text-xs overflow-hidden"
      role="radiogroup"
      aria-label="Color theme"
    >
      {(["light", "system", "dark"] as Theme[]).map((t) => (
        <button
          key={t}
          type="button"
          role="radio"
          aria-checked={theme === t}
          onClick={() => choose(t)}
          className={`px-2 py-1 capitalize ${
            theme === t
              ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
              : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
