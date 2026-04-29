"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { verifyMagicLink } from "@/lib/api";
import { useUser } from "@/lib/auth";

function VerifyContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { refresh } = useUser();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = searchParams.get("token");
    if (!token) {
      setError("Missing token");
      return;
    }
    verifyMagicLink(token)
      .then(() => refresh())
      .then(() => router.push("/"))
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Verification failed")
      );
  }, [searchParams, refresh, router]);

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center dark:border-red-900 dark:bg-red-950">
          <p className="text-red-800 dark:text-red-200">{error}</p>
          <a
            href="/login"
            className="mt-4 inline-block text-sm text-zinc-600 underline dark:text-zinc-400"
          >
            Try again
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <p className="text-zinc-500 dark:text-zinc-400">Verifying...</p>
    </div>
  );
}

export default function VerifyPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <p className="text-zinc-500 dark:text-zinc-400">Loading...</p>
        </div>
      }
    >
      <VerifyContent />
    </Suspense>
  );
}
