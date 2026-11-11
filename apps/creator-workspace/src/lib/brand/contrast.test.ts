import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import { contrastRatio, readThemeTokens } from "@/lib/brand/contrast";

const css = readFileSync(new URL("../../app/globals.css", import.meta.url), "utf8");
const t = readThemeTokens(css);

describe("contrastRatio", () => {
  test("matches WCAG reference values", () => {
    expect(contrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21, 1);
    expect(contrastRatio("#043B65", "#FFFFFF")).toBeCloseTo(11.55, 1);
  });

  test("is symmetric", () => {
    expect(contrastRatio("#FFFFFF", "#043B65")).toBeCloseTo(contrastRatio("#043B65", "#FFFFFF"), 6);
  });
});

describe("brand tokens (spec section 3.1)", () => {
  test.each([
    ["pdm-ink", "pdm-card"],
    ["pdm-ink", "pdm-canvas"],
    ["pdm-heading", "pdm-canvas"],
    ["pdm-muted", "pdm-card"],
    ["pdm-muted", "pdm-canvas"],
    ["pdm-muted", "pdm-primary-tint"],
    ["pdm-primary", "pdm-primary-tint"],
    ["pdm-success-text", "pdm-success-tint"],
    ["pdm-ai-text", "pdm-ai-tint"],
    ["pdm-money-text", "pdm-money-tint"],
    ["pdm-danger-text", "pdm-danger-tint"],
    ["pdm-ink", "pdm-human"],
  ])("%s on %s passes AA text (4.5:1)", (fg, bg) => {
    expect(t[fg], fg).toBeDefined();
    expect(t[bg], bg).toBeDefined();
    expect(contrastRatio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5);
  });

  test("white on primary and primary-hover passes AA", () => {
    expect(contrastRatio("#FFFFFF", t["pdm-primary"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#FFFFFF", t["pdm-primary-hover"])).toBeGreaterThanOrEqual(4.5);
  });

  test("input border passes AA non-text (3:1)", () => {
    expect(contrastRatio(t["pdm-border-strong"], t["pdm-card"])).toBeGreaterThanOrEqual(3);
  });

  test("brand colours are pinned to the style guide", () => {
    expect(t["pdm-heading"]).toBe("#043B65");
    expect(t["pdm-ink"]).toBe("#12232E");
    expect(t["pdm-success"]).toBe("#17A770");
    expect(t["pdm-ai"]).toBe("#0DBED6");
    expect(t["pdm-money"]).toBe("#DB8424");
  });
});
