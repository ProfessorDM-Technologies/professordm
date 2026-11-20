import type { Metadata, Viewport } from "next";
import { Montserrat } from "next/font/google";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { parseTheme, THEME_COOKIE } from "@/lib/theme";
import "./globals.css";

// Brand heading face (guide §04). Body copy uses Aptos or the system sans, so no second webfont.
const montserrat = Montserrat({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-montserrat",
  display: "swap",
});

export const metadata: Metadata = {
  title: { template: "%s | ProfessorDM Creator Workspace", default: "ProfessorDM Creator Workspace" },
  description: "Review, answer and track the questions your followers send you.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Read on the server so the first paint already has the saved theme (no flash).
  const theme = parseTheme((await cookies()).get(THEME_COOKIE)?.value);

  return (
    <html lang="en" data-theme={theme} className={montserrat.variable}>
      <body className="bg-pdm-surface font-sans text-pdm-ink antialiased">{children}</body>
    </html>
  );
}
