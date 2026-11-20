/* eslint-disable @next/next/no-img-element -- static SVG/WebP brand assets; next/image adds nothing here */
import Link from "next/link";

// Icon mark + vector wordmark (DESIGN.md "Logo"). No background: it sits straight on the page.
// The dark wordmark sets "Professor" in white so it stays legible on navy; the light one uses brand navy.
export function BrandLogo({ className = "" }: { className?: string }) {
  return (
    <Link
      href="/"
      aria-label="ProfessorDM Creator Workspace, home"
      className={`inline-flex items-center gap-2.5 rounded-xl p-1 ${className}`}
    >
      <img
        src="/brand/mark.webp"
        alt=""
        width={278}
        height={192}
        className="h-8 w-auto lg:h-10"
      />
      <span className="flex flex-col">
        <img src="/brand/wordmark-light.svg" alt="" width={530} height={96} className="h-4 w-auto dark:hidden lg:h-5" />
        <img src="/brand/wordmark-dark.svg" alt="" width={530} height={96} className="hidden h-4 w-auto dark:block lg:h-5" />
        <span className="mt-0.5 text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-pdm-muted">
          Creator Workspace
        </span>
      </span>
    </Link>
  );
}
