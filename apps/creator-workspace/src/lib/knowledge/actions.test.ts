import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ refresh: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createClient: vi.fn() }));

import { refresh } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { setEntryPublished } from "./actions";

const entryId = "11111111-1111-4111-8111-111111111111";

function publishForm(published = "true", id = entryId) {
  const data = new FormData();
  data.set("entry_id", id);
  data.set("published", published);
  return data;
}

describe("setEntryPublished", () => {
  const rpc = vi.fn();

  beforeEach(() => {
    rpc.mockReset();
    vi.mocked(refresh).mockClear();
    vi.mocked(createClient).mockResolvedValue({ rpc } as unknown as Awaited<ReturnType<typeof createClient>>);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("publishes through the database function and refreshes", async () => {
    rpc.mockResolvedValue({ data: "updated", error: null });
    expect(await setEntryPublished({ status: "idle" }, publishForm("true"))).toEqual({ status: "done" });
    expect(rpc).toHaveBeenCalledWith("set_knowledge_entry_published", { p_entry_id: entryId, p_published: true });
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("makes an entry private", async () => {
    rpc.mockResolvedValue({ data: "updated", error: null });
    await setEntryPublished({ status: "idle" }, publishForm("false"));
    expect(rpc).toHaveBeenCalledWith("set_knowledge_entry_published", { p_entry_id: entryId, p_published: false });
  });

  it("treats an entry already in that state as done", async () => {
    rpc.mockResolvedValue({ data: "unchanged", error: null });
    expect(await setEntryPublished({ status: "idle" }, publishForm())).toEqual({ status: "done" });
  });

  it("does not call the database for a malformed form", async () => {
    const result = await setEntryPublished({ status: "idle" }, publishForm("maybe"));
    expect(result).toEqual({ status: "error", message: "This change couldn't be saved. Refresh the page and try again." });
    expect(rpc).not.toHaveBeenCalled();
  });

  it("shows a plain message and does not refresh when the database refuses", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    rpc.mockResolvedValue({ data: null, error: { code: "P0002", message: "not_found" } });
    expect(await setEntryPublished({ status: "idle" }, publishForm())).toEqual({
      status: "error",
      message: "This entry is unavailable for your account. Refresh the page.",
    });
    expect(refresh).not.toHaveBeenCalled();
  });
});
