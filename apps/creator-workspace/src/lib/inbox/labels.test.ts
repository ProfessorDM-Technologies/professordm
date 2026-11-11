import { INBOUND_MESSAGE_STATUS, MESSAGE_CATEGORIES, OUTBOUND_TYPES, QUESTION_STATUS } from "@professordm/contracts";
import { describe, expect, it } from "vitest";
import {
  isCreatorAuthored,
  KNOWLEDGE_COVERAGE,
  NO_DRAFT_REASONS,
  UNCLASSIFIED_LABEL,
  categoryLabel,
  coverageLabel,
  flagLabel,
  inboundStatusLabel,
  noDraftReasonLabel,
  outboundStatusLabel,
  outboundTypeLabel,
  questionStatusLabel,
} from "./labels";

describe("categoryLabel", () => {
  it("has a label for every category in contracts", () => {
    for (const category of MESSAGE_CATEGORIES) {
      expect(categoryLabel(category)).not.toBe(UNCLASSIFIED_LABEL);
    }
  });

  it("falls back for null and unknown values", () => {
    expect(categoryLabel(null)).toBe(UNCLASSIFIED_LABEL);
    expect(categoryLabel("not_a_category")).toBe(UNCLASSIFIED_LABEL);
  });

  it("uses readable names", () => {
    expect(categoryLabel("expert_question")).toBe("Expert Question");
    expect(categoryLabel("spam_irrelevant")).toBe("Spam");
  });
});

describe("inboundStatusLabel", () => {
  it("has a label for every status in contracts", () => {
    for (const status of INBOUND_MESSAGE_STATUS) {
      expect(inboundStatusLabel(status)).toBeTruthy();
    }
  });

  it("returns null for null and unknown values", () => {
    expect(inboundStatusLabel(null)).toBeNull();
    expect(inboundStatusLabel("nope")).toBeNull();
  });
});

describe("outboundTypeLabel", () => {
  it("has a label for every outbound type in contracts", () => {
    for (const type of OUTBOUND_TYPES) {
      expect(outboundTypeLabel(type)).not.toBe(type);
    }
  });

  it("shows unknown types as they are", () => {
    expect(outboundTypeLabel("carrier_pigeon")).toBe("carrier_pigeon");
  });
});

describe("outboundStatusLabel", () => {
  it("makes free-text statuses readable", () => {
    expect(outboundStatusLabel("delivered")).toBe("Delivered");
    expect(outboundStatusLabel("delivery_failed")).toBe("Delivery failed");
  });

  it("returns null when there is no status", () => {
    expect(outboundStatusLabel(null)).toBeNull();
    expect(outboundStatusLabel(undefined)).toBeNull();
    expect(outboundStatusLabel("")).toBeNull();
  });
});

describe("questionStatusLabel", () => {
  it("has a label for every question status in contracts", () => {
    for (const status of QUESTION_STATUS) {
      expect(questionStatusLabel(status)).toBeTruthy();
    }
  });

  it("returns null for null and unknown values", () => {
    expect(questionStatusLabel(null)).toBeNull();
    expect(questionStatusLabel("nope")).toBeNull();
  });
});

describe("coverageLabel", () => {
  it("uses the plain-language sentences", () => {
    expect(coverageLabel("high")).toBe("Well covered by your guides");
    expect(coverageLabel("partial")).toBe("Partly covered by your guides");
    expect(coverageLabel("none")).toBe("Not in your guides");
    expect(KNOWLEDGE_COVERAGE.every((value) => coverageLabel(value))).toBe(true);
  });

  it("returns null for null and unknown values", () => {
    expect(coverageLabel(null)).toBeNull();
    expect(coverageLabel("total")).toBeNull();
  });
});

describe("noDraftReasonLabel", () => {
  it("has a sentence for every reason", () => {
    expect(noDraftReasonLabel("no_coverage")).toBe("Your guides don't cover this yet");
    expect(noDraftReasonLabel("invalid_output")).toBe("The AI draft didn't pass its quality checks");
    expect(noDraftReasonLabel("safety_blocked")).toBe("The AI held back a draft for safety");
    expect(noDraftReasonLabel("empty_question")).toBe("The question had no text");
    expect(NO_DRAFT_REASONS.every((value) => noDraftReasonLabel(value))).toBe(true);
  });

  it("returns null for null and unknown values", () => {
    expect(noDraftReasonLabel(null)).toBeNull();
    expect(noDraftReasonLabel("other")).toBeNull();
  });
});

describe("flagLabel", () => {
  it("names the known flags in plain language", () => {
    expect(flagLabel({ layer: "moderation", category: "harassment", detail: null })).toBe("Harassing language");
    expect(flagLabel({ layer: "policy", category: "safety_concern", detail: null })).toBe("Safety concern");
  });

  it("adds the risk topic detail", () => {
    expect(flagLabel({ layer: "policy", category: "risk_topic", detail: "pet_toxicity" })).toBe(
      "Sensitive topic: pet toxicity",
    );
    expect(flagLabel({ layer: "policy", category: "risk_topic", detail: null })).toBe("Sensitive topic");
  });

  it("falls back to the category for anything else", () => {
    expect(flagLabel({ layer: "moderation", category: "self_harm", detail: null })).toBe("Flagged: self harm");
    expect(flagLabel({ layer: "rules", category: "harassment", detail: null })).toBe("Flagged: harassment");
    expect(flagLabel({ layer: null, category: null, detail: null })).toBe("Flagged");
  });
});

describe("isCreatorAuthored", () => {
  it("is true only for the creator's own answers and follow-ups", () => {
    expect(isCreatorAuthored("answer")).toBe(true);
    expect(isCreatorAuthored("followup")).toBe(true);
  });

  it("is false for automated messages and unknown or missing types", () => {
    for (const type of ["ask_link", "clarification", "confirmation", "rating_prompt", "survey", "decline", "other"]) {
      expect(isCreatorAuthored(type)).toBe(false);
    }
    expect(isCreatorAuthored(undefined)).toBe(false);
  });
});
