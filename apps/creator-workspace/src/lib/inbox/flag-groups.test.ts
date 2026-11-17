import { describe, expect, it } from "vitest";
import { groupFlagsByQuestion, type FlagRow } from "./flag-groups";

const flag = (id: string, target_type: string, target_id: string): FlagRow => ({
  id,
  target_type,
  target_id,
  checkpoint: null,
  layer: null,
  category: null,
  detail: null,
  status: "open",
});
const question = (id: string, origin_message_id: string | null) => ({ id, origin_message_id });
const noDrafts = new Map<string, string>();

describe("groupFlagsByQuestion", () => {
  it("merges a message flag and a draft flag on one question", () => {
    const groups = groupFlagsByQuestion(
      [flag("f1", "message", "m1"), flag("f2", "draft", "d1")],
      [question("q1", "m1")],
      new Map([["d1", "q1"]]),
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].question.id).toBe("q1");
    expect(groups[0].flags.map((f) => f.id)).toEqual(["f1", "f2"]);
    expect(groups[0].flags.map((f) => f.targetType)).toEqual(["message", "draft"]);
  });

  it("drops a flag on a message with no question", () => {
    expect(groupFlagsByQuestion([flag("f1", "message", "m9")], [question("q1", "m1")], noDrafts)).toEqual([]);
  });

  it("drops a draft flag whose draft is unknown", () => {
    expect(groupFlagsByQuestion([flag("f1", "draft", "d9")], [question("q1", "m1")], noDrafts)).toEqual([]);
  });

  it("keeps the question order and skips unflagged questions", () => {
    const groups = groupFlagsByQuestion(
      [flag("f1", "message", "m1"), flag("f2", "message", "m2")],
      [question("q2", "m2"), question("q1", "m1"), question("q3", "m3")],
      noDrafts,
    );
    expect(groups.map((g) => g.question.id)).toEqual(["q2", "q1"]);
  });

  it("returns nothing when there are no flags", () => {
    expect(groupFlagsByQuestion([], [question("q1", "m1")], noDrafts)).toEqual([]);
  });
});
