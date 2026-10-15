import { describe, expect, it } from "vitest";
import { FREE_ANSWER_LIMIT, freeAnswersLeft } from "./free-answers";

describe("freeAnswersLeft", () => {
  it("starts at the limit for a new account", () => {
    expect(FREE_ANSWER_LIMIT).toBe(5);
    expect(freeAnswersLeft(0)).toBe(5);
  });

  it("counts down as answers are used", () => {
    expect(freeAnswersLeft(2)).toBe(3);
    expect(freeAnswersLeft(4)).toBe(1);
  });

  it("never goes below zero", () => {
    expect(freeAnswersLeft(5)).toBe(0);
    expect(freeAnswersLeft(9)).toBe(0);
  });

  it("treats missing or invalid values as nothing used", () => {
    expect(freeAnswersLeft(null)).toBe(5);
    expect(freeAnswersLeft(undefined)).toBe(5);
    expect(freeAnswersLeft(Number.NaN)).toBe(5);
    expect(freeAnswersLeft(-3)).toBe(5);
  });

  it("ignores fractions", () => {
    expect(freeAnswersLeft(2.7)).toBe(3);
  });
});
