// Initial-letter avatar for an Instagram sender. Decorative: the username is always written next to it.
export function Avatar({ username, size = "md" }: { username: string | null; size?: "sm" | "md" }) {
  const letter = username?.replace(/^@/, "").charAt(0).toUpperCase() || "?";
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center rounded-full bg-linear-to-br from-pdm-cyan to-pdm-teal font-display font-bold text-white ring-2 ring-pdm-panel ${
        size === "sm" ? "size-9 text-sm" : "size-11 text-base"
      }`}
    >
      {letter}
    </span>
  );
}
