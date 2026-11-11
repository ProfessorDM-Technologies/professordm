import type { NavIconName } from "@/lib/nav";

// Simple 20px line icons for the mobile tab bar (brand guide section 05: clean line icons over clip-art).
const PATHS: Record<NavIconName, string> = {
  bank: "M3 10h18M5 10v8m4-8v8m6-8v8m4-8v8M3 20h18M12 3l9 5H3z",
  incoming: "M12 3v11m0 0-4-4m4 4 4-4M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4",
  inbox: "M3 13h5l1.5 3h5l1.5-3h5M5.5 5h13l2.5 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z",
  sent: "M21 3 10 14M21 3l-6.5 18-4.5-7-7-4.5z",
  moderation: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6zm-3 9 2 2 4-4",
  knowledge: "M4 19V5a2 2 0 0 1 2-2h14v14H6a2 2 0 0 0-2 2 2 2 0 0 0 2 2h14M8 7h8",
  profile: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-8 9a8 8 0 0 1 16 0",
};

export function NavIcon({ name, className = "size-5" }: { name: NavIconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
