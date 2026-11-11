import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import { contrastRatio, readThemeTokens } from "@/lib/brand/contrast";

const css = readFileSync(new URL("../../app/globals.css", import.meta.url), "utf8");

describe("contrastRatio", () => {
  test("matches WCAG reference values", () => {
    expect(contrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21, 1);
    expect(contrastRatio("#043B65", "#FFFFFF")).toBeCloseTo(11.55, 1);
  });

  test("is symmetric", () => {
    expect(contrastRatio("#FFFFFF", "#043B65")).toBeCloseTo(contrastRatio("#043B65", "#FFFFFF"), 6);
  });
});

const TEXT_PAIRS = [
  ["pdm-ink", "pdm-card"],
  ["pdm-ink", "pdm-canvas"],
  ["pdm-heading", "pdm-canvas"],
  ["pdm-muted", "pdm-card"],
  ["pdm-muted", "pdm-canvas"],
  ["pdm-muted", "pdm-primary-tint"],
  ["pdm-primary", "pdm-primary-tint"],
  ["pdm-primary", "pdm-card"],
  ["pdm-success-text", "pdm-success-tint"],
  ["pdm-ai-text", "pdm-ai-tint"],
  ["pdm-money-text", "pdm-money-tint"],
  ["pdm-danger-text", "pdm-danger-tint"],
  ["pdm-danger-text", "pdm-card"],
  ["pdm-ink", "pdm-human"],
  ["pdm-on-primary", "pdm-primary"],
  ["pdm-on-primary", "pdm-primary-hover"],
] as const;

describe.each(["light", "dark"] as const)("%s theme tokens (spec section 3.1 / v2 dark palette)", (mode) => {
  const t = readThemeTokens(css, mode);

  test.each(TEXT_PAIRS)("%s on %s passes AA text (4.5:1)", (fg, bg) => {
    expect(t[fg], fg).toBeDefined();
    expect(t[bg], bg).toBeDefined();
    expect(contrastRatio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
  });

  test("input border passes AA non-text (3:1)", () => {
    expect(contrastRatio(t["pdm-border-strong"], t["pdm-card"])).toBeGreaterThanOrEqual(3);
  });

  test("the logo background stays white", () => {
    expect(t["pdm-logo-bg"]).toBe("#FFFFFF");
  });

  test("brand fills are unchanged", () => {
    expect(t["pdm-success"]).toBe("#17A770");
    expect(t["pdm-ai"]).toBe("#0DBED6");
    expect(t["pdm-money"]).toBe("#DB8424");
  });
});

describe("light theme pins the style guide", () => {
  test("navy values", () => {
    const t = readThemeTokens(css, "light");
    expect(t["pdm-heading"]).toBe("#043B65");
    expect(t["pdm-ink"]).toBe("#12232E");
  });
});

describe("dark theme", () => {
  test("uses Midnight Navy for cards and actually differs from light", () => {
    const light = readThemeTokens(css, "light");
    const dark = readThemeTokens(css, "dark");
    expect(dark["pdm-card"]).toBe("#12232E");
    expect(dark["pdm-canvas"]).not.toBe(light["pdm-canvas"]);
  });
});
