"use client";

const FORMAT = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

// Formats in the viewer's time zone. The server renders in UTC, so the text can differ
// between server and browser; suppressHydrationWarning keeps React from complaining.
export function LocalTime({ value, className }: { value: string; className?: string }) {
  return (
    <time dateTime={value} className={className} suppressHydrationWarning>
      {FORMAT.format(new Date(value))}
    </time>
  );
}
