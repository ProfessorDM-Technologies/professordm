import type { Metadata, Viewport } from "next";
import { Montserrat } from "next/font/google";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { parseTheme, THEME_COOKIE } from "@/lib/theme";
import "./globals.css";

// Brand heading face. Body copy uses Aptos or the system sans, so no second webfont.
const montserrat = Montserrat({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-montserrat",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ProfessorDM",
  description: "Expert answers to the questions you send in your DMs.",
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
