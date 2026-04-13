import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-screen bg-zinc-50 text-zinc-900`}
      >
        <header className="border-b border-zinc-200 bg-white">
          <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
            <Link href="/" className="font-semibold tracking-tight">
              EFTA <span className="text-zinc-500 font-normal">· research tool</span>
            </Link>
            <nav className="text-sm text-zinc-600 flex gap-4">
              <Link href="/" className="hover:text-zinc-900">Search</Link>
              <a
                href="https://www.justice.gov/epstein/doj-disclosures"
                target="_blank"
                rel="noreferrer"
                className="hover:text-zinc-900"
              >
                DOJ source
              </a>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
        <footer className="mx-auto max-w-6xl px-6 py-10 text-xs text-zinc-500">
          Public DOJ documents only. Victim names are never displayed.
          Search results may contain noise; verify against the original PDF.
        </footer>
      </body>
    </html>
  );
}
