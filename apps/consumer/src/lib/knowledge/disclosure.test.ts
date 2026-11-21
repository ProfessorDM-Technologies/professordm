import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AiDisclosure } from "@/components/ai-disclosure";
import { EntryCard } from "@/components/entry-card";
import { AI_DISCLOSURE } from "./disclosure";

const entry = { id: "a", title: "Why are my leaves yellow?", content: "Water less.", tags: ["watering"] };

describe("AI disclosure", () => {
  it("says the creator approved it and AI helped", () => {
    expect(AI_DISCLOSURE.full).toMatch(/Sweetlife Flora/);
    expect(AI_DISCLOSURE.full).toMatch(/AI/);
    expect(AI_DISCLOSURE.full).toMatch(/not professional advice/);
    expect(AI_DISCLOSURE.short).toMatch(/AI/);
  });

  it("renders the full text for the answer page", () => {
    expect(renderToStaticMarkup(createElement(AiDisclosure, { variant: "full" }))).toContain(AI_DISCLOSURE.full);
  });

  it("shows the short label on every search card", () => {
    expect(renderToStaticMarkup(createElement(EntryCard, { entry }))).toContain(AI_DISCLOSURE.short);
  });
});
