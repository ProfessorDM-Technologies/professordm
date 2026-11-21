import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const metadata: Metadata = {
  title: "Page not found",
};

// Any URL no other workspace route matches lands here, so its 404 renders inside the workspace shell
// (not-found.tsx next to the layout) instead of the bare root 404. Specific routes always win over this.
export default function MissingPage() {
  notFound();
}
