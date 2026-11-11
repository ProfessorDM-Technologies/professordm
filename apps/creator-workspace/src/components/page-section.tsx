import type { ReactNode } from "react";

// Headings use Montserrat in Professor Navy through the base styles in globals.css (spec section 3.2).
export function PageHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-2">
      <h1 className="text-[1.75rem] leading-[2.125rem] font-bold tracking-[-0.01em]">{title}</h1>
      <p className="max-w-[70ch] text-pdm-muted">{description}</p>
    </div>
  );
}

export function PageSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-3">
      <h2 id={`${id}-heading`} className="text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}
