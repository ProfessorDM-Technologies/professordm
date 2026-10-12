import { INBOUND_MESSAGE_STATUS, MESSAGE_CATEGORIES, OUTBOUND_TYPES } from "@professordm/contracts";
import { describe, expect, it } from "vitest";
import {
  UNCLASSIFIED_LABEL,
  categoryLabel,
  inboundStatusLabel,
  outboundStatusLabel,
  outboundTypeLabel,
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
