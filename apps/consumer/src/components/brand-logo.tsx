/* eslint-disable @next/next/no-img-element -- static SVG/WebP brand assets; next/image adds nothing here */
import Link from "next/link";

// Icon mark + vector wordmark (DESIGN.md "Logo"). No background: it sits straight on the page.
// The dark wordmark sets "Professor" in white so it stays legible on navy; the light one uses brand navy.
export function BrandLogo({ className = "" }: { className?: string }) {
  return (
    <Link
      href="/"
      aria-label="ProfessorDM Ask Sweetlife Flora, home"
      className={`inline-flex items-center gap-2.5 rounded-xl p-1 ${className}`}
    >
      <img
        src="/brand/mark.webp"
        alt=""
        width={278}
        height={192}
        className="h-9 w-auto xl:h-12"
      />
      <span className="flex flex-col items-start">
        <img src="/brand/wordmark-light.svg" alt="" width={530} height={96} className="h-[1.125rem] w-auto dark:hidden xl:h-6" />
        <img src="/brand/wordmark-dark.svg" alt="" width={530} height={96} className="hidden h-[1.125rem] w-auto dark:block xl:h-6" />
        <span className="mt-0.5 text-[0.6875rem] font-semibold whitespace-nowrap uppercase tracking-[0.14em] text-pdm-muted">
          Ask Sweetlife Flora
        </span>
      </span>
    </Link>
  );
}
