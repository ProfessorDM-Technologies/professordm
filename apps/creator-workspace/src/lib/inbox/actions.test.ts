import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/cache", () => ({ refresh: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({ createClient: vi.fn() }));

import { createClient } from "@/lib/supabase/server";
import { sendReply } from "./actions";

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
});
