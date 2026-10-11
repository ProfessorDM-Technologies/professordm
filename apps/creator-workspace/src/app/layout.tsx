import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: { template: "%s | ProfessorDM Creator Workspace", default: "ProfessorDM Creator Workspace" },
  description: "Review, answer and track the questions your followers send you.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-pdm-surface font-sans text-pdm-ink antialiased">{children}</body>
    </html>
  );
}
