import type { MetadataRoute } from "next";

// A private, signed-in workspace: nothing here should be crawled (pages also send noindex).
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", disallow: "/" } };
}
