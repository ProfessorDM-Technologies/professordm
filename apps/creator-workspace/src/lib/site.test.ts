import { describe, expect, it } from "vitest";
import { siteUrl } from "./site";

describe("siteUrl", () => {
  it("uses NEXT_PUBLIC_SITE_URL first", () => {
    expect(
      siteUrl({ NEXT_PUBLIC_SITE_URL: "https://creators.example.com", VERCEL_PROJECT_PRODUCTION_URL: "x.vercel.app" }).href,
    ).toBe("https://creators.example.com/");
  });

  it("falls back to the Vercel production domain", () => {
    expect(siteUrl({ VERCEL_PROJECT_PRODUCTION_URL: "professordm-creator-workspace.vercel.app" }).href).toBe(
      "https://professordm-creator-workspace.vercel.app/",
    );
  });

  it("falls back to the local dev server", () => {
    expect(siteUrl({}).href).toBe("http://localhost:3001/");
    expect(siteUrl({ NEXT_PUBLIC_SITE_URL: "  " }).href).toBe("http://localhost:3001/");
  });
});
