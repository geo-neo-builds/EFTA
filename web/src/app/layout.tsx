import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";
import { AuthProvider } from "@/lib/auth";
import { HeaderAuth } from "@/components/HeaderAuth";
import Notepad from "@/components/Notepad";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "EFTA — Epstein Files Research Tool",
  description:
    "Search and explore publicly released DOJ Epstein case documents.",
};

// Runs before React hydrates so the right theme class is on <html> on first
// paint. Prevents a light-mode flash when the user prefers dark.
const themeInitScript = `
  (function() {
    try {
      var s = localStorage.getItem('efta-theme') || 'system';
      var d = s === 'dark' ||
              (s === 'system' &&
               window.matchMedia('(prefers-color-scheme: dark)').matches);
      if (d) document.documentElement.classList.add('dark');
    } catch (e) {}
  })();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100`}
      >
        <AuthProvider>
          <header className="border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
            <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
              <Link href="/" className="font-semibold tracking-tight">
                EFTA{" "}
                <span className="text-zinc-500 dark:text-zinc-400 font-normal">
                  · research tool
                </span>
              </Link>
              <nav className="text-sm text-zinc-600 dark:text-zinc-300 flex gap-4 items-center">
                <Link href="/" className="hover:text-zinc-900 dark:hover:text-white">
                  Search
                </Link>
                <Link href="/timeline" className="hover:text-zinc-900 dark:hover:text-white">
                  Timeline
                </Link>
                <a
                  href="https://www.justice.gov/epstein/doj-disclosures"
                  target="_blank"
                  rel="noreferrer"
                  className="hover:text-zinc-900 dark:hover:text-white"
                >
                  DOJ source
                </a>
                <ThemeToggle />
                <HeaderAuth />
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
          <footer className="mx-auto max-w-6xl px-6 py-10 text-xs text-zinc-500 dark:text-zinc-500">
            Public DOJ documents only. Victim names are never displayed.
            Search results may contain noise; verify against the original PDF.
          </footer>
          <Notepad />
        </AuthProvider>
      </body>
    </html>
  );
}
