import { describe, expect, it } from "vitest";
import { groupMessagesByQuestion } from "./message-threads";

const message = (id: string, text: string | null, receivedAt: string, followerId = "fA") => ({
  id,
  text,
  receivedAt,
  follower: { id: followerId },
});

const question = message("m1", "Is my monstera safe for my cat?", "2026-11-17T10:00:00Z");
const reply = message("m2", "Monstera deliciosa", "2026-11-17T10:05:00Z");
const round = { messageId: "m1", round: 1, reply: "Monstera deliciosa" };

const ids = (threads: ReturnType<typeof groupMessagesByQuestion<ReturnType<typeof message>>>) =>
  threads.map((thread) => [thread.head.id, ...thread.replies.map((r) => r.id)]);

describe("groupMessagesByQuestion", () => {
  it("folds a clarification reply under its question", () => {
    const threads = groupMessagesByQuestion([reply, question], [round]);
    expect(ids(threads)).toEqual([["m1", "m2"]]);
    expect(threads[0].latestAt).toBe("2026-11-17T10:05:00Z");
  });

  it("keeps a message with no matching round as its own thread", () => {
    const other = message("m3", "love your page!!", "2026-11-17T09:00:00Z");
    expect(ids(groupMessagesByQuestion([question, other], []))).toEqual([["m1"], ["m3"]]);
  });

  it("only folds replies from the same sender", () => {
    const strangerReply = message("m2", "Monstera deliciosa", "2026-11-17T10:05:00Z", "fB");
    expect(ids(groupMessagesByQuestion([question, strangerReply], [round]))).toEqual([["m2"], ["m1"]]);
  });

  it("does not fold a matching message sent before the question", () => {
    const earlier = message("m0", "Monstera deliciosa", "2026-11-17T09:00:00Z");
    expect(ids(groupMessagesByQuestion([question, earlier], [round]))).toEqual([["m1"], ["m0"]]);
  });

  it("uses each message for one reply only", () => {
    const yes1 = message("m2", "yes", "2026-11-17T10:05:00Z");
    const yes2 = message("m3", "yes", "2026-11-17T10:06:00Z");
    const threads = groupMessagesByQuestion([question, yes1, yes2], [{ messageId: "m1", round: 1, reply: "yes" }]);
    expect(ids(threads)).toEqual([["m3"], ["m1", "m2"]]);
  });

  it("folds two rounds in round order", () => {
    const second = message("m3", "about two years old", "2026-11-17T10:09:00Z");
    const threads = groupMessagesByQuestion(
      [second, reply, question],
      [
        { messageId: "m1", round: 2, reply: "about two years old" },
        { messageId: "m1", round: 1, reply: "Monstera deliciosa" },
      ],
    );
    expect(ids(threads)).toEqual([["m1", "m2", "m3"]]);
  });

  it("puts the thread with the newest activity first", () => {
    const older = message("m5", "What soil for a ficus?", "2026-11-16T08:00:00Z", "fB");
    const lateReply = message("m6", "indoors", "2026-11-17T12:00:00Z", "fB");
    const threads = groupMessagesByQuestion(
      [question, reply, older, lateReply],
      [round, { messageId: "m5", round: 1, reply: "indoors" }],
    );
    expect(ids(threads)).toEqual([["m5", "m6"], ["m1", "m2"]]);
  });

  it("ignores a round with no reply yet", () => {
    expect(ids(groupMessagesByQuestion([question], [{ messageId: "m1", round: 1, reply: null }]))).toEqual([["m1"]]);
  });
});
