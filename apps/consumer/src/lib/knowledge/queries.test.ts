import { beforeEach, describe, expect, it, vi } from "vitest";

type Call = { method: string; args: unknown[] };

const state = vi.hoisted(() => ({
  calls: [] as { method: string; args: unknown[] }[],
  result: { data: null as unknown, error: null as unknown },
}));

vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => {
    const query: Record<string, unknown> = {};
    for (const method of ["select", "eq", "order", "limit", "maybeSingle", "overrideTypes"]) {
      query[method] = (...args: unknown[]) => {
        state.calls.push({ method, args });
        return query;
      };
    }
    query.then = (resolve: (value: unknown) => unknown) => resolve(state.result);
    return {
      from: (table: string) => {
        state.calls.push({ method: "from", args: [table] });
        return query;
      },
    };
  },
}));

const { getPublishedEntries, getPublishedEntry, getPublishedTags } = await import("./queries");

const ID = "808fe679-e6b6-4fc8-8252-f581c4f1bd15";

function called(method: string): Call[] {
  return state.calls.filter((call) => call.method === method);
}

function selectedColumns() {
  return String(called("select")[0]?.args[0] ?? "")
    .split(",")
    .map((column) => column.trim());
}

beforeEach(() => {
  state.calls.length = 0;
  state.result = { data: [], error: null };
});

describe("published-only reads", () => {
  it("lists only published entries", async () => {
    await getPublishedEntries();
    expect(called("from")[0]?.args).toEqual(["knowledge_entries"]);
    expect(called("eq")).toContainEqual({ method: "eq", args: ["published", true] });
  });

  it("reads topics from published entries only", async () => {
    await getPublishedTags();
    expect(selectedColumns()).toEqual(["tags"]);
    expect(called("eq")).toContainEqual({ method: "eq", args: ["published", true] });
  });

  it("opens one entry only when it is published", async () => {
    state.result = { data: { id: ID, title: "t", content: "c", tags: [] }, error: null };
    await getPublishedEntry(ID);
    expect(called("eq")).toContainEqual({ method: "eq", args: ["id", ID] });
    expect(called("eq")).toContainEqual({ method: "eq", args: ["published", true] });
  });

  it("returns nothing for an entry that is private or missing", async () => {
    state.result = { data: null, error: null };
    expect(await getPublishedEntry(ID)).toBeNull();
  });

  it("does not query at all for an id that is not a uuid", async () => {
    expect(await getPublishedEntry("not-a-uuid")).toBeNull();
    expect(state.calls).toEqual([]);
  });
});

describe("no follower details", () => {
  it("selects only the question, answer and tags", async () => {
    await getPublishedEntries();
    expect(selectedColumns()).toEqual(["id", "title", "content", "tags"]);
  });

  it("selects the same columns for a single entry", async () => {
    await getPublishedEntry(ID);
    expect(selectedColumns()).toEqual(["id", "title", "content", "tags"]);
  });

  it("never asks for question, follower or DM fields", async () => {
    await getPublishedEntries();
    await getPublishedEntry(ID);
    const requested = called("select").map((call) => String(call.args[0]));
    for (const columns of requested) {
      expect(columns).not.toMatch(/\*|question|follower|handle|message|creator_id|published/);
    }
  });

  it("hides database error details from the page", async () => {
    state.result = { data: null, error: { message: "permission denied for table knowledge_entries" } };
    await expect(getPublishedEntries()).rejects.toThrow("Could not load answers");
    await expect(getPublishedEntry(ID)).rejects.toThrow("Could not load this answer");
  });
});
