// WCAG 2.1 contrast helpers, used by tests to keep the brand tokens in globals.css accessible.

function channel(value: number) {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string) {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) throw new Error(`Expected a #RRGGBB colour, got ${hex}`);
  const n = Number.parseInt(match[1], 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrastRatio(foreground: string, background: string): number {
  const [hi, lo] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}

/** Maps `--color-pdm-*` hex declarations in a CSS string to `{ "pdm-ink": "#12232E", ... }`. */
export function readThemeTokens(css: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  for (const [, name, hex] of css.matchAll(/--color-(pdm-[a-z-]+):\s*(#[0-9a-fA-F]{6})\b/g)) {
    tokens[name] = hex;
  }
  return tokens;
}
