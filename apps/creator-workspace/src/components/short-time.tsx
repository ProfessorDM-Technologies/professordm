"use client";

const FULL = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const DAY = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

// Relative to `now` (when the page data was read). "now", "5m", "3h", "2d", then "Nov 4", like a messaging list. Rendered in the viewer's clock, so the server
// text can differ; suppressHydrationWarning keeps React quiet. The full time is in the title.
export function ShortTime({ value, now, className }: { value: string; now: number; className?: string }) {
  const date = new Date(value);
  const minutes = Math.max(0, Math.round((now - date.getTime()) / 60000));
  const label =
    minutes < 1
      ? "now"
      : minutes < 60
        ? `${minutes}m`
        : minutes < 60 * 24
          ? `${Math.round(minutes / 60)}h`
          : minutes < 60 * 24 * 7
            ? `${Math.round(minutes / 1440)}d`
            : DAY.format(date);

  return (
    <time dateTime={value} title={FULL.format(date)} className={className} suppressHydrationWarning>
      {label}
    </time>
  );
}
