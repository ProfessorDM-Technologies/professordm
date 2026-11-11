// One style for clickable cards (inbox, sent, moderation, incoming): a subtle lift and navy edge on hover.
const CARD_LINK =
  "block space-y-2 rounded-xl border border-pdm-border bg-pdm-card p-4 motion-safe:transition-[border-color,translate,box-shadow] motion-safe:duration-150 hover:border-pdm-primary motion-safe:hover:-translate-y-px hover:shadow-[0_10px_24px_-16px_rgb(4_59_101/0.45)]";

export function cardLinkClass(extra?: string): string {
  return extra ? `${CARD_LINK} ${extra}` : CARD_LINK;
}
