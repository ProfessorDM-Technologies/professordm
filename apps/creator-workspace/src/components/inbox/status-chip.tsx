import type { CardTone } from "@/lib/inbox/question-state";

const TONE_STYLES: Record<CardTone, string> = {
  // Cyan = AI and questions in motion (brand §03); teal tint = ready for you; red = needs care.
  progress: "bg-pdm-cyan-tint text-pdm-cyan-ink",
  danger: "bg-pdm-danger-bg text-pdm-danger-ink",
  accent: "bg-pdm-tint text-pdm-accent-strong",
  neutral: "bg-pdm-subtle text-pdm-ink",
};

// The label is always text, so colour is never the only signal. The dot pulses only when motion is allowed.
export function StatusChip({ label, tone, pulse = tone === "progress" }: { label: string; tone: CardTone; pulse?: boolean }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${TONE_STYLES[tone]}`}
    >
      {pulse ? <span aria-hidden="true" className="size-1.5 rounded-full bg-pdm-cyan motion-safe:animate-pulse" /> : null}
      {label}
    </span>
  );
}
