import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

const appRoot = new URL("../../../", import.meta.url);

// Width and height live in the PNG IHDR chunk, bytes 16-23, big-endian.
function pngSize(relativePath: string) {
  const bytes = readFileSync(new URL(relativePath, appRoot));
  expect(bytes.subarray(1, 4).toString("ascii"), `${relativePath} is a PNG`).toBe("PNG");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

describe("brand assets (spec section 5)", () => {
  test("full logo keeps the original 620:490 proportions", () => {
    const { width, height } = pngSize("public/brand/pdm-logo.png");
    expect(width).toBeGreaterThanOrEqual(620);
    expect(width / height).toBeCloseTo(620 / 490, 2);
  });

  test("icon mark is large enough for a 2x 36px tile", () => {
    const { width, height } = pngSize("public/brand/pdm-icon.png");
    expect(height).toBeGreaterThanOrEqual(72 * 2);
    expect(width).toBeGreaterThan(height);
  });

  test("favicon is 512 square", () => {
    expect(pngSize("src/app/icon.png")).toEqual({ width: 512, height: 512 });
  });
});
