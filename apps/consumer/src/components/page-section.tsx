import type { ReactNode } from "react";

export function PageHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-2">
      <h1 className="text-3xl leading-tight font-extrabold sm:text-4xl">{title}</h1>
      <p className="max-w-prose text-pdm-muted">{description}</p>
    </div>
  );
}

export function PageSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-3">
      <h2 id={`${id}-heading`} className="text-lg font-bold">
        {title}
      </h2>
      {children}
    </section>
  );
}
