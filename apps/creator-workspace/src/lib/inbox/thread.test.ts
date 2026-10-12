import { describe, expect, it } from "vitest";
import { buildThread, type ThreadClarification, type ThreadInbound, type ThreadOutbound } from "./thread";

const inbound = (id: string, receivedAt: string, text = id): ThreadInbound => ({ id, text, receivedAt });
const outbound = (id: string, sentAt: string | null, type = "answer"): ThreadOutbound => ({
  id,
  text: id,
  sentAt,
  type,
  status: "delivered",
});
const round = (id: string, messageId: string, n: number, reply: string | null = `reply-${n}`): ThreadClarification => ({
  id,
  messageId,
  round: n,
  prompt: `prompt-${n}`,
  reply,
});

const keys = (items: ReturnType<typeof buildThread>) => items.map((item) => item.key);

describe("buildThread", () => {
  it("returns an empty list when there is nothing", () => {
    expect(buildThread({ inbound: [], clarifications: [], outbound: [] })).toEqual([]);
  });

  it("orders inbound and outbound by time, whatever order they arrive in", () => {
    const items = buildThread({
      inbound: [inbound("m2", "2026-10-03T00:00:00Z"), inbound("m1", "2026-10-01T00:00:00Z")],
      clarifications: [],
      outbound: [outbound("a1", "2026-10-02T00:00:00Z")],
    });

    expect(keys(items)).toEqual(["in-m1", "out-a1", "in-m2"]);
    expect(items.map((item) => item.direction)).toEqual(["in", "out", "in"]);
  });

  it("puts clarification prompt then reply right after their message, in round order", () => {
    const items = buildThread({
      inbound: [inbound("m1", "2026-10-01T00:00:00Z"), inbound("m2", "2026-10-02T00:00:00Z")],
      clarifications: [round("r2", "m1", 2), round("r1", "m1", 1)],
      outbound: [],
    });

    expect(keys(items)).toEqual(["in-m1", "cp-r1", "cr-r1", "cp-r2", "cr-r2", "in-m2"]);
    expect(items[1]).toMatchObject({ direction: "out", kind: "clarification_prompt", text: "prompt-1" });
    expect(items[2]).toMatchObject({ direction: "in", kind: "clarification_reply", text: "reply-1" });
  });

  it("skips a clarification reply that hasn't arrived yet", () => {
    const items = buildThread({
      inbound: [inbound("m1", "2026-10-01T00:00:00Z")],
      clarifications: [round("r1", "m1", 1, null)],
      outbound: [],
    });

    expect(keys(items)).toEqual(["in-m1", "cp-r1"]);
  });

  it("puts sends with no time last", () => {
    const items = buildThread({
      inbound: [inbound("m1", "2026-10-01T00:00:00Z")],
      clarifications: [],
      outbound: [outbound("late", null), outbound("a1", "2026-10-02T00:00:00Z")],
    });

    expect(keys(items)).toEqual(["in-m1", "out-a1", "out-late"]);
  });

  it("puts inbound before outbound when the times are equal", () => {
    const items = buildThread({
      inbound: [inbound("m1", "2026-10-01T00:00:00Z")],
      clarifications: [],
      outbound: [outbound("a1", "2026-10-01T00:00:00Z")],
    });

    expect(keys(items)).toEqual(["in-m1", "out-a1"]);
  });

  it("carries outbound type and status through", () => {
    const [item] = buildThread({ inbound: [], clarifications: [], outbound: [outbound("f1", "2026-10-01T00:00:00Z", "followup")] });

    expect(item).toMatchObject({ kind: "outbound", outboundType: "followup", status: "delivered" });
  });
});
