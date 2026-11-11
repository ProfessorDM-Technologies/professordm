import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

// Keeps the creator workspace on the ProfessorDM brand tokens (docs/plans/creator-brand-refresh-spec.md, section 7).
const srcDir = fileURLToPath(new URL("../../", import.meta.url));
const cssPath = fileURLToPath(new URL("../../app/globals.css", import.meta.url));

function tsxFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return tsxFiles(path);
    return entry.name.endsWith(".tsx") ? [path] : [];
  });
}

// Raw Tailwind palette colours, black, the retired amber-era tokens, and the banned radius.
const OFF_BRAND =
  /\b(?:bg|text|border|ring|divide|outline)-(?:stone|red|green|amber|gray|slate)-\d|\bbg-(?:black|white)\b|\btext-white\b|pdm-(?:accent|tint\b|surface)|rounded-2xl/g;

const files = tsxFiles(srcDir);

describe("brand palette guard", () => {
  test("finds the app's components", () => {
    expect(files.length).toBeGreaterThan(30);
  });

  test.each(files.map((file) => relative(srcDir, file)))("%s uses brand tokens only", (file) => {
    const source = readFileSync(join(srcDir, file), "utf8");
    expect(source.match(OFF_BRAND) ?? []).toEqual([]);
  });

  test("globals.css no longer defines the legacy aliases", () => {
    const css = readFileSync(cssPath, "utf8");
    expect(css).not.toMatch(/--color-pdm-(?:accent|tint|surface)\b/);
  });
});
