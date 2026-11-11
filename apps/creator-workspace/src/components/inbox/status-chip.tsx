import type { CardTone } from "@/lib/inbox/question-state";

// Tones follow the brand's colour meanings (spec section 3.1): cyan = AI at work, navy = ready for you,
// teal = done, red = needs attention. Text always uses the AA-safe "-text" shades.
const TONE_STYLES: Record<CardTone, { chip: string; dot: string }> = {
  progress: { chip: "bg-pdm-ai-tint text-pdm-ai-text", dot: "bg-pdm-ai" },
  accent: { chip: "bg-pdm-primary-tint text-pdm-primary", dot: "bg-pdm-primary" },
  success: { chip: "bg-pdm-success-tint text-pdm-success-text", dot: "bg-pdm-success" },
  danger: { chip: "bg-pdm-danger-tint text-pdm-danger-text", dot: "bg-pdm-danger-text" },
  neutral: { chip: "bg-white text-pdm-muted ring-1 ring-pdm-border", dot: "bg-pdm-muted" },
};

// The label is always text, so colour is never the only signal. The dot pulses only when motion is allowed.
export function StatusChip({ label, tone, pulse = tone === "progress" }: { label: string; tone: CardTone; pulse?: boolean }) {
  const style = TONE_STYLES[tone];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${style.chip}`}
    >
      {pulse ? <span aria-hidden="true" className={`size-1.5 rounded-full motion-safe:animate-pulse ${style.dot}`} /> : null}
      {label}
    </span>
  );
}
