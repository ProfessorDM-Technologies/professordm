export default function SignedInLoading() {
  return (
    <div className="space-y-6" aria-busy="true">
      <p className="sr-only" role="status">
        Loading answers…
      </p>
      <div aria-hidden="true" className="space-y-2">
        <div className="h-8 w-64 max-w-full rounded bg-pdm-subtle motion-safe:animate-pulse" />
        <div className="h-4 w-80 max-w-full rounded bg-pdm-subtle motion-safe:animate-pulse" />
      </div>
      <ul aria-hidden="true" className="space-y-3">
        {[0, 1, 2].map((key) => (
          <li key={key} className="space-y-3 rounded-2xl border border-pdm-border bg-pdm-panel p-4">
            <div className="h-4 w-2/3 rounded bg-pdm-subtle motion-safe:animate-pulse" />
            <div className="h-3 w-11/12 rounded bg-pdm-subtle motion-safe:animate-pulse" />
            <div className="h-3 w-1/2 rounded bg-pdm-subtle motion-safe:animate-pulse" />
            <div className="flex gap-2">
              <div className="h-5 w-16 rounded-full bg-pdm-subtle motion-safe:animate-pulse" />
              <div className="h-5 w-20 rounded-full bg-pdm-subtle motion-safe:animate-pulse" />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
