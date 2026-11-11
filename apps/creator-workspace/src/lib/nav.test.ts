import { describe, expect, test } from "vitest";
import { NAV_ITEMS, inboxBadgeText, isActive, mobileNavItems } from "@/lib/nav";

describe("isActive", () => {
  test("root only matches exactly", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/inbox", "/")).toBe(false);
  });

  test("nested routes match their section", () => {
    expect(isActive("/inbox/question/abc", "/inbox")).toBe(true);
    expect(isActive("/inboxes", "/inbox")).toBe(false);
  });
});

describe("nav items", () => {
  test("mobile bar keeps the five thumb items in order", () => {
    expect(mobileNavItems().map((i) => i.label)).toEqual(["Bank", "Incoming", "Inbox", "Sent", "Moderation"]);
  });

  test("island has six sections (Profile lives in the avatar menu), each with an icon", () => {
    expect(NAV_ITEMS.map((i) => i.label)).toEqual(["Bank", "Incoming", "Inbox", "Sent", "Moderation", "Knowledge"]);
    expect(NAV_ITEMS.every((i) => i.icon)).toBe(true);
  });
});

describe("inboxBadgeText", () => {
  test("hides for zero or unknown counts", () => {
    expect(inboxBadgeText(0)).toBeNull();
    expect(inboxBadgeText(null)).toBeNull();
    expect(inboxBadgeText(undefined)).toBeNull();
  });

  test("shows the count and caps at 99+", () => {
    expect(inboxBadgeText(7)).toBe("7");
    expect(inboxBadgeText(99)).toBe("99");
    expect(inboxBadgeText(120)).toBe("99+");
  });
});
