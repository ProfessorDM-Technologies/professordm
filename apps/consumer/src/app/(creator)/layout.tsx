import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: { template: "%s | Ask Sweetlife Flora", default: "Ask Sweetlife Flora" },
  description: "Verified plant care answers from Sweetlife Flora.",
};

export default function CreatorLayout({ children }: { children: ReactNode }) {
  return <div className="min-h-dvh bg-flora-surface text-flora-ink">{children}</div>;
}
