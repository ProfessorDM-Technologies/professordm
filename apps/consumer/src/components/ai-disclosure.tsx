import { AI_DISCLOSURE } from "@/lib/knowledge/disclosure";

export function AiDisclosure({ variant }: { variant: "full" | "short" }) {
  if (variant === "short") {
    return <p className="mt-3 text-xs font-medium text-flora-muted">{AI_DISCLOSURE.short}</p>;
  }
  return <p className="border-t border-flora-border pt-4 text-sm text-flora-muted">{AI_DISCLOSURE.full}</p>;
}
