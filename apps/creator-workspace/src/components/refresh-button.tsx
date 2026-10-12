"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

export function RefreshButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <button
      type="button"
      onClick={() => startTransition(() => router.refresh())}
      disabled={pending}
      className="min-h-11 rounded-lg border border-pdm-border bg-white px-4 text-sm font-medium hover:bg-pdm-surface disabled:opacity-60"
    >
      {pending ? "Refreshing…" : "Refresh"}
    </button>
  );
}
