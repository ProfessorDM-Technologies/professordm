import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/cache", () => ({ refresh: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createClient: vi.fn() }));

import { refresh } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { approveAnswer, sendReply } from "./actions";

const inboundId = "11111111-1111-4111-8111-111111111111";
const requestId = "22222222-2222-4222-8222-222222222222";

function form() {
  const data = new FormData();
  data.set("inbound_message_id", inboundId);
  data.set("client_request_id", requestId);
  data.set("text", "A manual reply");
  return data;
}

describe("sendReply API handoff", () => {
  beforeEach(() => {
    process.env.INSTAGRAM_SEND_API_URL = "https://api.example.invalid/api/send";
    vi.mocked(createClient).mockResolvedValue({
      auth: {
        getUser: vi.fn().mockResolvedValue({ data: { user: { id: "creator-user" } }, error: null }),
        getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: "synthetic-user-jwt" } }, error: null }),
      },
    } as unknown as Awaited<ReturnType<typeof createClient>>);
  });

  afterEach(() => {
    delete process.env.INSTAGRAM_SEND_API_URL;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("forwards only the user JWT and reply fields to the API", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "sent" }) });
    vi.stubGlobal("fetch", fetchMock);
    const result = await sendReply({ status: "idle" }, form());
    expect(result).toEqual({ status: "sent", clientRequestId: requestId });
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.invalid/api/send");
    expect(options.headers.Authorization).toBe("Bearer synthetic-user-jwt");
    expect(JSON.parse(options.body)).toEqual({
      inbound_message_id: inboundId,
      text: "A manual reply",
      client_request_id: requestId,
    });
  });

  it("does not call the API without an authenticated user", async () => {
    vi.mocked(createClient).mockResolvedValue({
      auth: { getUser: vi.fn().mockResolvedValue({ data: { user: null }, error: null }) },
    } as unknown as Awaited<ReturnType<typeof createClient>>);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await sendReply({ status: "idle" }, form());
    expect(result.status).toBe("error");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not send the session token to a non-HTTPS API URL", async () => {
    process.env.INSTAGRAM_SEND_API_URL = "http://api.example.invalid/api/send";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await sendReply({ status: "idle" }, form());
    expect(result.status).toBe("error");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps a failed duplicate request as an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "failed" }) }));
    const result = await sendReply({ status: "idle" }, form());
    expect(result.status).toBe("error");
  });

  it("reports an in-flight duplicate as pending rather than sent", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "pending" }) }));
    expect(await sendReply({ status: "idle" }, form())).toEqual({ status: "pending", clientRequestId: requestId });
  });

  it("refreshes the thread after an ambiguous network failure", async () => {
    vi.mocked(refresh).mockClear();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private network detail")));
    const result = await sendReply({ status: "idle" }, form());
    expect(result.status).toBe("error");
    expect(JSON.stringify(result)).not.toContain("private network detail");
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("does not forward provider error details to the creator", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({ error: "private provider detail" }) }));
    const result = await sendReply({ status: "idle" }, form());
    expect(result.status).toBe("error");
    expect(JSON.stringify(result)).not.toContain("private provider detail");
  });

  it("gives a useful message when the backend rejects an expired session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    const result = await sendReply({ status: "idle" }, form());
    expect(result).toEqual({ status: "error", message: "Your session expired. Sign in again before sending." });
  });
});

const questionId = "33333333-3333-4333-8333-333333333333";
const flagId = "44444444-4444-4444-8444-444444444444";

function answerForm({ tags = ["Calathea", "light"], flags = [flagId] }: { tags?: string[]; flags?: string[] } = {}) {
  const data = new FormData();
  data.set("question_id", questionId);
  data.set("inbound_message_id", inboundId);
  data.set("client_request_id", requestId);
  data.set("text", "  My edited answer  ");
  for (const tag of tags) data.append("tags", tag);
  for (const flag of flags) data.append("reviewed_flag_ids", flag);
  return data;
}

const respond = (status: number, body?: unknown) =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => {
        if (body === undefined) throw new SyntaxError("no body");
        return body;
      },
    }),
  );

describe("approveAnswer API handoff", () => {
  beforeEach(() => {
    process.env.INSTAGRAM_SEND_API_URL = "https://api.example.invalid/api/send";
    vi.mocked(createClient).mockResolvedValue({
      auth: {
        getUser: vi.fn().mockResolvedValue({ data: { user: { id: "creator-user" } }, error: null }),
        getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: "synthetic-user-jwt" } }, error: null }),
      },
    } as unknown as Awaited<ReturnType<typeof createClient>>);
  });

  afterEach(() => {
    delete process.env.INSTAGRAM_SEND_API_URL;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("posts question_id, tags and reviewed_flag_ids with the session token", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: "sent" }) });
    vi.stubGlobal("fetch", fetchMock);
    const result = await approveAnswer({ status: "idle" }, answerForm());

    expect(result.status).toBe("sent");
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example.invalid/api/send");
    expect(options.headers.Authorization).toBe("Bearer synthetic-user-jwt");
    expect(JSON.parse(options.body)).toEqual({
      inbound_message_id: inboundId,
      text: "My edited answer",
      client_request_id: requestId,
      question_id: questionId,
      tags: ["calathea", "light"],
      reviewed_flag_ids: [flagId],
    });
  });

  it("gives a new request id after success", async () => {
    respond(200, { status: "sent" });
    const result = await approveAnswer({ status: "idle" }, answerForm());
    expect(result).toMatchObject({ status: "sent" });
    expect(result.status !== "idle" && result.nextClientRequestId).not.toBe(requestId);
  });

  it("keeps the request id while the send is pending", async () => {
    respond(200, { status: "pending" });
    expect(await approveAnswer({ status: "idle" }, answerForm())).toEqual({
      status: "pending",
      nextClientRequestId: requestId,
    });
  });

  it.each([
    [422, "edit_required", "Edit the draft so it's in your words before sending."],
    [422, "tags_required", "Add at least one tag."],
    [422, "flags_unreviewed", "Review the safety flags first."],
    [409, "not_awaiting_answer", "This question was already answered. Refresh to see it."],
    [502, "delivery_failed", "Instagram didn't accept the message. Your answer is saved. Try again in a minute."],
  ])("maps %i %s to a plain sentence and a new request id", async (status, error, message) => {
    respond(status, { error });
    const result = await approveAnswer({ status: "idle" }, answerForm());
    expect(result).toMatchObject({ status: "error", message });
    expect(result.status === "error" && result.nextClientRequestId).not.toBe(requestId);
  });

  it("gives the session message on 401", async () => {
    respond(401);
    expect(await approveAnswer({ status: "idle" }, answerForm())).toMatchObject({
      status: "error",
      message: "Your session expired. Sign in again before sending.",
    });
  });

  it("keeps the request id after a network error, without leaking details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private network detail")));
    const result = await approveAnswer({ status: "idle" }, answerForm());
    expect(result).toMatchObject({ status: "error", nextClientRequestId: requestId });
    expect(JSON.stringify(result)).not.toContain("private network detail");
  });

  it("keeps the request id after a 503 and doesn't forward provider details", async () => {
    respond(503, { error: "private provider detail" });
    const result = await approveAnswer({ status: "idle" }, answerForm());
    expect(result).toMatchObject({ status: "error", nextClientRequestId: requestId });
    expect(JSON.stringify(result)).not.toContain("private provider detail");
  });

  it("does not call the API when the form fails validation", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const result = await approveAnswer({ status: "idle" }, answerForm({ tags: [] }));
    expect(result).toMatchObject({ status: "error", message: "Add at least one tag." });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not call the API without an authenticated user", async () => {
    vi.mocked(createClient).mockResolvedValue({
      auth: { getUser: vi.fn().mockResolvedValue({ data: { user: null }, error: null }) },
    } as unknown as Awaited<ReturnType<typeof createClient>>);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect((await approveAnswer({ status: "idle" }, answerForm())).status).toBe("error");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
