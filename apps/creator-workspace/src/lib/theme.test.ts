import { describe, expect, test } from "vitest";
import { THEME_STORAGE_KEY, parseThemePref, resolveTheme, themeBootScript } from "@/lib/theme";

describe("parseThemePref", () => {
  test("accepts the three stored values", () => {
    expect(parseThemePref("light")).toBe("light");
    expect(parseThemePref("dark")).toBe("dark");
    expect(parseThemePref("system")).toBe("system");
  });

  test("falls back to system for missing or unknown values", () => {
    expect(parseThemePref(null)).toBe("system");
    expect(parseThemePref("")).toBe("system");
    expect(parseThemePref("purple")).toBe("system");
  });
});

describe("resolveTheme", () => {
  test("an explicit choice wins over the device", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  test("system follows the device", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
});

describe("themeBootScript", () => {
  test("reads the same storage key and sets data-theme before paint", () => {
    expect(themeBootScript).toContain(JSON.stringify(THEME_STORAGE_KEY));
    expect(themeBootScript).toContain("data-theme");
    expect(themeBootScript).toContain("prefers-color-scheme: dark");
  });

  test("never throws when storage is blocked", () => {
    expect(themeBootScript).toMatch(/try\s*\{/);
  });
});
