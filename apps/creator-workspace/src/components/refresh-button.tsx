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
      className="pdm-press min-h-11 rounded-full border border-pdm-border bg-pdm-panel px-4 text-sm font-semibold hover:border-pdm-accent hover:bg-pdm-subtle disabled:opacity-60"
    >
      {pending ? "Refreshing…" : "Refresh"}
    </button>
  );
}
