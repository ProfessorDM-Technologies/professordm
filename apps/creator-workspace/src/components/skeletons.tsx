import { Page } from "@/components/page";

// Skeletons shown the instant a route is clicked (UI v2 spec, motion b). They match the real layouts' widths and
// heights so nothing jumps when content arrives. Purely visual: screen readers get one status line instead.
const BAR = "rounded bg-pdm-border/60 motion-safe:animate-pulse";

export function ListSkeleton({ label, rows = 3, tabs = false }: { label: string; rows?: number; tabs?: boolean }) {
  return (
    <Page className="space-y-6" aria-busy>
      <p className="sr-only" role="status">
        {label}
      </p>
      <div aria-hidden="true" className="space-y-2">
        <div className={`h-8 w-40 ${BAR}`} />
        <div className={`h-4 w-72 max-w-full ${BAR}`} />
      </div>
      {tabs ? (
        <div aria-hidden="true" className="flex gap-3 border-b border-pdm-border pb-3">
          <div className={`h-6 w-20 ${BAR}`} />
          <div className={`h-6 w-16 ${BAR}`} />
          <div className={`h-6 w-24 ${BAR}`} />
        </div>
      ) : null}
      <ul aria-hidden="true" className="space-y-3">
        {Array.from({ length: rows }, (_, key) => (
          <li key={key} className="space-y-3 rounded-xl border border-pdm-border bg-pdm-card p-4">
            <div className="flex justify-between gap-3">
              <div className={`h-4 w-32 ${BAR}`} />
              <div className={`h-4 w-24 rounded-full ${BAR}`} />
            </div>
            <div className={`h-3 w-11/12 ${BAR}`} />
            <div className={`h-3 w-2/3 ${BAR}`} />
          </li>
        ))}
      </ul>
    </Page>
  );
}

/** The conversation / question pane while it loads; the chat rail beside it stays on screen. */
export function PaneSkeleton({ label }: { label: string }) {
  return (
    <div
      aria-busy="true"
      className="flex h-[calc(100dvh-17.25rem)] min-h-[26rem] flex-col overflow-hidden rounded-xl border border-pdm-border bg-pdm-card md:h-[calc(100dvh-13.25rem)] lg:h-[calc(100dvh-10rem)]"
    >
      <p className="sr-only" role="status">
        {label}
      </p>
      <div aria-hidden="true" className="flex items-center gap-3 border-b border-pdm-border px-4 py-3">
        <div className={`size-10 rounded-full ${BAR}`} />
        <div className="space-y-2">
          <div className={`h-4 w-36 ${BAR}`} />
          <div className={`h-3 w-24 ${BAR}`} />
        </div>
      </div>
      <div aria-hidden="true" className="flex-1 space-y-4 px-4 py-5">
        <div className={`h-12 w-2/3 rounded-xl ${BAR}`} />
        <div className={`ml-auto h-20 w-3/5 rounded-xl ${BAR}`} />
        <div className={`h-10 w-1/2 rounded-xl ${BAR}`} />
      </div>
      <div aria-hidden="true" className="border-t border-pdm-border p-3">
        <div className={`h-11 w-full rounded-xl ${BAR}`} />
      </div>
    </div>
  );
}
