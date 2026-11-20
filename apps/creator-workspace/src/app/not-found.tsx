import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center space-y-4 px-4 py-10 text-center">
      <p className="font-display text-sm font-bold tracking-wide text-pdm-accent-strong uppercase">ProfessorDM</p>
      <h1 className="text-3xl font-extrabold">Page not found</h1>
      <p className="text-pdm-muted">That page doesn&apos;t exist in the Creator Workspace.</p>
      <p>
        <Link href="/" className="font-semibold text-pdm-accent-strong underline underline-offset-4">
          Go to ProfessorDM Bank
        </Link>
      </p>
    </main>
  );
}
