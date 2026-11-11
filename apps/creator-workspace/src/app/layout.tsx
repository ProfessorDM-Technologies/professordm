import type { Metadata, Viewport } from "next";
import { Inter, Montserrat } from "next/font/google";
import type { ReactNode } from "react";
import { themeBootScript } from "@/lib/theme";
import "./globals.css";

// Brand type (spec section 3.2): Montserrat for headings and nav, Aptos then Inter for body. Self-hosted by next/font.
const montserrat = Montserrat({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-montserrat", display: "swap" });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

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
    // suppressHydrationWarning: the boot script sets data-theme on <html> before React hydrates.
    <html lang="en" className={`${montserrat.variable} ${inter.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body className="bg-pdm-canvas font-sans text-pdm-ink antialiased">{children}</body>
    </html>
  );
}
