import Image from "next/image";

// Logo usage rules (spec section 5, brand guide section 02):
// - Never re-type "ProfessorDM" as a logo; always render these images.
// - Both source PNGs have opaque white backgrounds, so they only ever sit on white (the tile or a white card).
// - Never stretch: dimensions follow the source aspect ratio.

const ICON = { src: "/brand/pdm-icon.png", width: 512, height: 359 } as const;
const LOGO = { src: "/brand/pdm-logo.png", width: 620, height: 490 } as const;

const TILE_SIZES = { sm: "size-8", md: "size-9" } as const;

/** Icon mark on a white tile. Decorative: the surrounding link carries the accessible name. */
export function BrandMark({ size = "md" }: { size?: keyof typeof TILE_SIZES }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-lg border border-pdm-border bg-white p-1 ${TILE_SIZES[size]}`}
    >
      <Image src={ICON.src} width={ICON.width} height={ICON.height} alt="" className="h-auto w-full" preload />
    </span>
  );
}

/** Full stacked logo with wordmark, for login and 404. */
export function BrandLogo({ width }: { width: number }) {
  const height = Math.round((width * LOGO.height) / LOGO.width);
  return <Image src={LOGO.src} width={width} height={height} alt="ProfessorDM" preload />;
}
