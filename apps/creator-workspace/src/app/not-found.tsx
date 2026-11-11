import Link from "next/link";
import { BrandLogo } from "@/components/brand/brand-mark";
import { BrandMist } from "@/components/brand/brand-mist";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col items-center justify-center space-y-4 px-4 py-10 text-center">
      <BrandMist />
      <BrandLogo width={160} />
      <h1 className="text-[1.75rem] leading-[2.125rem] font-bold tracking-[-0.01em]">Page not found</h1>
      <p className="text-pdm-muted">That page doesn&apos;t exist in the Creator Workspace.</p>
      <p>
        <Link href="/" className="font-semibold text-pdm-primary underline underline-offset-4">
          Go to ProfessorDM Bank
        </Link>
      </p>
    </main>
  );
}
