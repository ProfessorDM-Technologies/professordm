import { describe, expect, test } from "vitest";
import { buttonClass } from "@/components/ui/button-styles";

describe("buttonClass", () => {
  test("defaults to a navy primary button with a 44px target", () => {
    const classes = buttonClass();
    expect(classes).toContain("bg-pdm-primary");
    expect(classes).toContain("text-pdm-on-primary");
    expect(classes).toContain("min-h-11");
  });

  test("secondary small uses the strong border and a smaller target, never the primary fill", () => {
    const classes = buttonClass("secondary", "sm");
    expect(classes).toContain("border-pdm-border-strong");
    expect(classes).toContain("min-h-9");
    expect(classes).not.toContain("bg-pdm-primary");
  });

  test("danger uses the danger text colour as its fill", () => {
    expect(buttonClass("danger")).toContain("bg-pdm-danger-text");
  });

  test("every variant shows a disabled state", () => {
    for (const variant of ["primary", "secondary", "ghost", "danger"] as const) {
      expect(buttonClass(variant)).toContain("disabled:opacity-60");
    }
  });

  test("extra classes are appended last", () => {
    expect(buttonClass("primary", "md", "w-full").endsWith(" w-full")).toBe(true);
  });
});
