import { describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import { createPersistence } from "./persistence";
import type { InboundEvent } from "./meta";

const event: InboundEvent = {
  recipientIgUserId: "creator-ig-id", senderScopedId: "follower-scoped-id", mid: "meta-mid-1",
  text: "synthetic test text", receivedAt: "2026-10-12T00:00:00.000Z",
};

function query(result: unknown) {
  const builder = {
    select: vi.fn(), eq: vi.fn(), maybeSingle: vi.fn().mockResolvedValue(result),
    single: vi.fn().mockResolvedValue(result), upsert: vi.fn(), insert: vi.fn(),
  };
  for (const name of ["select", "eq", "upsert", "insert"] as const) builder[name].mockReturnValue(builder);
  return builder;
}

function client(...queries: ReturnType<typeof query>[]) {
  const from = vi.fn();
  queries.forEach((value) => from.mockReturnValueOnce(value));
  return { from } as unknown as SupabaseClient;
}

describe("Supabase persistence", () => {
  it("resolves the creator by ig_accounts.ig_user_id", async () => {
    const account = query({ data: { creator_id: "creator-uuid" }, error: null });
    expect(await createPersistence(client(account)).resolveCreator("creator-ig-id")).toBe("creator-uuid");
    expect(account.eq).toHaveBeenCalledWith("ig_user_id", "creator-ig-id");
  });

  it("upserts the follower by scoped ID with existing columns", async () => {
    const lookup = query({ data: null, error: null });
    const upsert = query({ data: { id: "follower-uuid", creator_id: "creator-uuid" }, error: null });
    expect(await createPersistence(client(lookup, upsert)).upsertFollower("creator-uuid", event)).toBe("follower-uuid");
    expect(upsert.upsert).toHaveBeenCalledWith({
      creator_id: "creator-uuid", ig_scoped_id: "follower-scoped-id", last_inbound_at: event.receivedAt,
    }, { onConflict: "ig_scoped_id" });
  });

  it("inserts a new message with received status and Meta mid", async () => {
    const insert = query({ data: { id: "message-uuid" }, error: null });
    expect(await createPersistence(client(insert)).insertOrGetMessage("follower-uuid", event)).toBe("message-uuid");
    expect(insert.insert).toHaveBeenCalledWith({
      follower_id: "follower-uuid", mid: "meta-mid-1", text: event.text,
      status: "received", received_at: event.receivedAt,
    });
  });

  it("returns the existing message UUID after a unique-mid conflict", async () => {
    const insert = query({ data: null, error: { code: "23505" } });
    const lookup = query({ data: { id: "message-uuid", follower_id: "follower-uuid" }, error: null });
    const database = client(insert, lookup);
    expect(await createPersistence(database).insertOrGetMessage("follower-uuid", event)).toBe("message-uuid");
    expect(lookup.eq).toHaveBeenCalledWith("mid", "meta-mid-1");
    expect(database.from).toHaveBeenCalledTimes(2);
  });

  it("does not create a second follower or message row on webhook retry", async () => {
    const followers: { id: string; creator_id: string; ig_scoped_id: string; last_inbound_at: string }[] = [];
    const messages: { id: string; follower_id: string; mid: string }[] = [];
    const database = {
      from(table: string) {
        const state: { operation?: string; value?: Record<string, string>; column?: string; match?: string } = {};
        const builder = {
          select() { return builder; },
          eq(column: string, match: string) { state.column = column; state.match = match; return builder; },
          upsert(value: Record<string, string>) { state.operation = "upsert"; state.value = value; return builder; },
          insert(value: Record<string, string>) { state.operation = "insert"; state.value = value; return builder; },
          async maybeSingle() {
            const rows = table === "ig_followers" ? followers : messages;
            return { data: rows.find((row) => row[state.column as keyof typeof row] === state.match) ?? null, error: null };
          },
          async single() {
            if (table === "ig_followers" && state.operation === "upsert") {
              let row = followers.find((item) => item.ig_scoped_id === state.value!.ig_scoped_id);
              if (!row) {
                row = { id: "follower-uuid", creator_id: state.value!.creator_id,
                  ig_scoped_id: state.value!.ig_scoped_id, last_inbound_at: state.value!.last_inbound_at };
                followers.push(row);
              }
              return { data: row, error: null };
            }
            if (table === "inbound_messages" && state.operation === "insert") {
              if (messages.some((item) => item.mid === state.value!.mid)) return { data: null, error: { code: "23505" } };
              const row = { id: "message-uuid", follower_id: state.value!.follower_id, mid: state.value!.mid };
              messages.push(row);
              return { data: row, error: null };
            }
            throw new Error("Unexpected test query");
          },
        };
        return builder;
      },
    } as unknown as SupabaseClient;
    const persistence = createPersistence(database);

    for (let attempt = 0; attempt < 2; attempt++) {
      const followerId = await persistence.upsertFollower("creator-uuid", event);
      expect(await persistence.insertOrGetMessage(followerId, event)).toBe("message-uuid");
    }
    expect(followers).toHaveLength(1);
    expect(messages).toHaveLength(1);
  });
});
