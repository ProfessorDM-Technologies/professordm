import { describe, expect, test } from "vitest";
import { pageWidthClass } from "@/components/page";

describe("pageWidthClass (UI v2 spec, requirement 5)", () => {
  test("list pages use a 768px reading column, centred", () => {
    expect(pageWidthClass("narrow")).toContain("max-w-3xl");
    expect(pageWidthClass("narrow")).toContain("mx-auto");
  });

  test("split views get room for two panes", () => {
    expect(pageWidthClass("wide")).toContain("max-w-6xl");
  });

  test("both fill the available width up to their cap", () => {
    expect(pageWidthClass("narrow")).toContain("w-full");
    expect(pageWidthClass("wide")).toContain("w-full");
  });
});

describe("pageWidthClass full", () => {
  test("inbox detail views get the widest column for rail + workspace", () => {
    expect(pageWidthClass("full")).toContain("max-w-7xl");
  });
});
