/* eslint-disable @next/next/no-img-element -- static brand assets */
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Page not found",
};

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col items-center justify-center px-4 py-10 text-center">
      <img src="/brand/mark.webp" alt="" width={278} height={192} className="h-16 w-auto" />
      <img src="/brand/wordmark-light.svg" alt="ProfessorDM" width={530} height={96} className="mt-3 h-6 w-auto dark:hidden" />
      <img src="/brand/wordmark-dark.svg" alt="ProfessorDM" width={530} height={96} className="mt-3 hidden h-6 w-auto dark:block" />
      <h1 className="mt-8 text-3xl font-extrabold">Page not found</h1>
      <p className="mt-3 text-pdm-muted">That page doesn&apos;t exist in Ask Sweetlife Flora.</p>
      <Link
        href="/"
        className="pdm-press mt-8 inline-flex min-h-11 items-center rounded-full bg-pdm-accent px-5 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong"
      >
        Go to Home
      </Link>
    </main>
  );
}
