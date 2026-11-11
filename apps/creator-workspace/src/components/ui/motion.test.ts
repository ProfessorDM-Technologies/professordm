import { createElement, type ComponentProps } from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { LiveItem, LiveList } from "@/components/ui/live-list";
import { buttonClass } from "@/components/ui/button-styles";
import { cardLinkClass } from "@/components/ui/card-styles";

describe("micro-interactions (UI v2 spec, motion)", () => {
  test("buttons press in, only when motion is allowed", () => {
    expect(buttonClass()).toContain("motion-safe:active:scale-[.98]");
  });

  test("clickable cards lift on hover, only when motion is allowed", () => {
    const classes = cardLinkClass();
    expect(classes).toContain("motion-safe:hover:-translate-y-px");
    expect(classes).toContain("hover:border-pdm-primary");
    expect(classes).toContain("rounded-xl");
  });

  test("cardLinkClass appends extra classes", () => {
    expect(cardLinkClass("group/card").endsWith(" group/card")).toBe(true);
  });
});

describe("LiveList", () => {
  test("items present on first render never animate (server HTML matches hydration)", () => {
    const html = renderToString(
      createElement(
        LiveList,
        { as: "ul" } as ComponentProps<typeof LiveList>,
        createElement(LiveItem, { className: "row" } as ComponentProps<typeof LiveItem>, "hello"),
      ),
    );
    expect(html).toContain("hello");
    expect(html).not.toContain("animate-rise-in");
    expect(html).toContain('class="row"');
  });
});
