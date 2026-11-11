// Three skeleton cards the height of a question card while the inbox loads (no spinner).
export default function InboxLoading() {
  return (
    <div className="space-y-6" aria-busy="true">
      <p className="sr-only" role="status">
        Loading questions…
      </p>
      <div aria-hidden="true" className="space-y-2">
        <div className="h-8 w-32 rounded bg-pdm-border/60 motion-safe:animate-pulse" />
        <div className="h-4 w-72 max-w-full rounded bg-pdm-border/60 motion-safe:animate-pulse" />
      </div>
      <ul aria-hidden="true" className="space-y-3">
        {[0, 1, 2].map((key) => (
          <li key={key} className="space-y-3 rounded-xl border border-pdm-border bg-white p-4">
            <div className="flex justify-between gap-3">
              <div className="h-4 w-32 rounded bg-pdm-border/60 motion-safe:animate-pulse" />
              <div className="h-4 w-24 rounded-full bg-pdm-border/60 motion-safe:animate-pulse" />
            </div>
            <div className="h-3 w-11/12 rounded bg-pdm-border/60 motion-safe:animate-pulse" />
            <div className="h-3 w-2/3 rounded bg-pdm-border/60 motion-safe:animate-pulse" />
            <div className="flex items-end justify-between gap-3">
              <div className="h-3 w-56 max-w-[60%] rounded bg-pdm-border/60 motion-safe:animate-pulse" />
              <div className="h-11 w-32 rounded-lg bg-pdm-border/60 motion-safe:animate-pulse" />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
