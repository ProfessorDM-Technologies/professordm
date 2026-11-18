export default function SignedInLoading() {
  return (
    <div className="space-y-6" aria-busy="true">
      <p className="sr-only" role="status">
        Loading answers…
      </p>
      <div aria-hidden="true" className="space-y-2">
        <div className="h-8 w-64 max-w-full rounded bg-flora-tint motion-safe:animate-pulse" />
        <div className="h-4 w-80 max-w-full rounded bg-flora-tint motion-safe:animate-pulse" />
      </div>
      <ul aria-hidden="true" className="space-y-3">
        {[0, 1, 2].map((key) => (
          <li key={key} className="space-y-3 rounded-lg border border-flora-border bg-white p-4">
            <div className="h-4 w-2/3 rounded bg-flora-tint motion-safe:animate-pulse" />
            <div className="h-3 w-11/12 rounded bg-flora-tint motion-safe:animate-pulse" />
            <div className="h-3 w-1/2 rounded bg-flora-tint motion-safe:animate-pulse" />
          </li>
        ))}
      </ul>
    </div>
  );
}
