export function SearchForm({ id, defaultValue }: { id: string; defaultValue?: string }) {
  return (
    <form action="/search" role="search" className="flex gap-2">
      <label htmlFor={id} className="sr-only">
        Search plant care answers
      </label>
      <input
        id={id}
        name="q"
        type="search"
        defaultValue={defaultValue}
        placeholder="Search plant care answers"
        className="block min-h-11 min-w-0 flex-1 rounded-full border border-pdm-border bg-pdm-panel px-4 py-2.5 text-base transition-colors placeholder:text-pdm-muted focus:border-pdm-accent"
      />
      <button
        type="submit"
        className="pdm-press min-h-11 shrink-0 rounded-full bg-pdm-accent px-5 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong"
      >
        Search
      </button>
    </form>
  );
}
