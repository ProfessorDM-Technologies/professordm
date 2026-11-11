// Faint fixed brand backdrop (spec section 4.3). It gives the frosted glass bars something to blur.
// Static and decorative: no animation, hidden from assistive tech, never intercepts pointer events.
const MIST = [
  "radial-gradient(40rem 22rem at 8% -4rem, color-mix(in srgb, var(--color-pdm-ai) 14%, transparent), transparent 70%)",
  "radial-gradient(36rem 20rem at 92% -2rem, color-mix(in srgb, var(--color-pdm-success) 10%, transparent), transparent 70%)",
  "radial-gradient(48rem 18rem at 50% -6rem, color-mix(in srgb, var(--color-pdm-primary) 6%, transparent), transparent 75%)",
].join(", ");

export function BrandMist() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-x-0 top-0 -z-10 h-[30rem]"
      style={{ backgroundImage: MIST }}
    />
  );
}
