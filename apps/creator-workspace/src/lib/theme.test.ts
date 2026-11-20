import { describe, expect, it } from "vitest";
import { parseTheme } from "./theme";

describe("parseTheme", () => {
  it("defaults to light", () => {
    expect(parseTheme(undefined)).toBe("light");
    expect(parseTheme("")).toBe("light");
    expect(parseTheme("system")).toBe("light");
  });

  it("keeps an explicit dark choice", () => {
    expect(parseTheme("dark")).toBe("dark");
  });
});
