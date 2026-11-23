import { AI_DISCLOSURE } from "@/lib/knowledge/disclosure";

export function AiDisclosure({ variant }: { variant: "full" | "short" }) {
  if (variant === "short") {
    return <p className="mt-3 text-xs font-semibold text-pdm-muted">{AI_DISCLOSURE.short}</p>;
  }
  return <p className="border-t border-pdm-border pt-4 text-sm text-pdm-muted">{AI_DISCLOSURE.full}</p>;
}
