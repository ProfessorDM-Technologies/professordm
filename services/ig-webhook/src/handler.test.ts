import { createHmac } from "node:crypto";
import type { APIGatewayProxyEventV2 } from "aws-lambda";
import { describe, expect, it, vi } from "vitest";
import { processWebhook, type Dependencies } from "./handler";
import { parseInboundEvents, verifyMetaSignature } from "./meta";

const secret = "test-secret-only";
const payload = {
  object: "instagram",
  entry: [{ messaging: [{
    recipient: { id: "creator-ig-id" }, sender: { id: "follower-scoped-id" },
    timestamp: 1_760_000_000_000, message: { mid: "meta-mid-1", text: "synthetic test text" },
  }] }],
};

function request(
  body: unknown = payload,
  signatureValid = true,
  base64Encoded = false,
  headerName = "X-Hub-Signature-256",
): APIGatewayProxyEventV2 {
  const raw = JSON.stringify(body);
  return {
    body: base64Encoded ? Buffer.from(raw).toString("base64") : raw,
    isBase64Encoded: base64Encoded,
    headers: { [headerName]: `sha256=${createHmac("sha256", signatureValid ? secret : "wrong")
      .update(Buffer.from(raw)).digest("hex")}` },
  } as unknown as APIGatewayProxyEventV2;
}

function dependencies(): Dependencies {
  return {
    appSecret: secret,
    persistence: {
      resolveCreator: vi.fn().mockResolvedValue("creator-uuid"),
      upsertFollower: vi.fn().mockResolvedValue("follower-uuid"),
      insertOrGetMessage: vi.fn().mockResolvedValue("message-uuid"),
    },
    queue: { send: vi.fn().mockResolvedValue(undefined) },
  };
}

describe("Meta verification and parsing", () => {
  it("accepts a valid signature over raw bytes and rejects invalid signatures", () => {
    const event = request();
    expect(verifyMetaSignature(Buffer.from(event.body!), event.headers["X-Hub-Signature-256"], secret)).toBe(true);
    expect(verifyMetaSignature(Buffer.from(event.body!), request(payload, false).headers["X-Hub-Signature-256"], secret)).toBe(false);
    expect(verifyMetaSignature(Buffer.from(event.body!), "sha256=bad", secret)).toBe(false);
    expect(verifyMetaSignature(Buffer.from(`${event.body} `), event.headers["X-Hub-Signature-256"], secret)).toBe(false);
  });

  it("ignores unsupported and echo events", () => {
    expect(parseInboundEvents({ object: "page", entry: payload.entry })).toEqual([]);
    expect(parseInboundEvents({ object: "instagram", entry: [{ messaging: [{
      recipient: { id: "creator-ig-id" }, sender: { id: "follower-scoped-id" },
      message: { mid: "x", is_echo: true },
    }] }] })).toEqual([]);
  });
});

describe("inbound webhook", () => {
  it("rejects a bad signature before persistence or SQS", async () => {
    const deps = dependencies();
    expect(await processWebhook(request(payload, false), deps)).toEqual({ statusCode: 401 });
    expect(deps.persistence.resolveCreator).not.toHaveBeenCalled();
    expect(deps.queue.send).not.toHaveBeenCalled();
  });

  it("looks up creator, persists the follower and message, then sends a triage envelope", async () => {
    const deps = dependencies();
    expect(await processWebhook(request(), deps)).toEqual({ statusCode: 200 });
    expect(deps.persistence.resolveCreator).toHaveBeenCalledWith("creator-ig-id");
    expect(deps.persistence.upsertFollower).toHaveBeenCalledWith("creator-uuid", expect.objectContaining({
      senderScopedId: "follower-scoped-id", receivedAt: new Date(1_760_000_000_000).toISOString(),
    }));
    expect(deps.persistence.insertOrGetMessage).toHaveBeenCalledWith("follower-uuid", expect.objectContaining({ mid: "meta-mid-1" }));
    expect(deps.queue.send).toHaveBeenCalledWith({
      v: 1, type: "triage", id: "triage:message-uuid", creatorId: "creator-uuid",
      traceId: expect.any(String), createdAt: expect.any(String), payload: { messageId: "message-uuid" },
    });
    expect(vi.mocked(deps.persistence.insertOrGetMessage).mock.invocationCallOrder[0])
      .toBeLessThan(vi.mocked(deps.queue.send).mock.invocationCallOrder[0]);
  });

  it("verifies base64 API Gateway bodies against decoded raw bytes and accepts lowercase header names", async () => {
    const deps = dependencies();
    const withUnicode = { object: "instagram", entry: [{ messaging: [{
      recipient: { id: "creator-ig-id" }, sender: { id: "follower-scoped-id" },
      message: { mid: "meta-mid-unicode", text: "synthetic café text" },
    }] }] };
    expect(await processWebhook(request(withUnicode, true, true, "x-hub-signature-256"), deps))
      .toEqual({ statusCode: 200 });
    expect(deps.persistence.insertOrGetMessage).toHaveBeenCalledWith("follower-uuid", expect.objectContaining({
      mid: "meta-mid-unicode", text: "synthetic café text",
    }));
  });

  it("returns 400 for signed malformed JSON without querying the database", async () => {
    const deps = dependencies();
    const raw = Buffer.from("{malformed-json");
    const event = request();
    event.body = raw.toString("utf8");
    event.headers["X-Hub-Signature-256"] = `sha256=${createHmac("sha256", secret).update(raw).digest("hex")}`;
    expect(await processWebhook(event, deps)).toEqual({ statusCode: 400 });
    expect(deps.persistence.resolveCreator).not.toHaveBeenCalled();
  });

  it("ignores unsupported and echo events without enqueueing", async () => {
    const deps = dependencies();
    expect(await processWebhook(request({ object: "page", entry: payload.entry }), deps))
      .toEqual({ statusCode: 200 });
    expect(await processWebhook(request({ object: "instagram", entry: [{ messaging: [{
      recipient: { id: "creator-ig-id" }, sender: { id: "follower-scoped-id" },
      message: { mid: "echo-mid", is_echo: true },
    }] }] }), deps)).toEqual({ statusCode: 200 });
    expect(deps.persistence.resolveCreator).not.toHaveBeenCalled();
    expect(deps.queue.send).not.toHaveBeenCalled();
  });

  it("fails safely when no creator account matches the recipient", async () => {
    const deps = dependencies();
    vi.mocked(deps.persistence.resolveCreator).mockResolvedValue(null);
    await expect(processWebhook(request(), deps)).rejects.toThrow("Instagram account is not connected");
    expect(deps.persistence.upsertFollower).not.toHaveBeenCalled();
    expect(deps.queue.send).not.toHaveBeenCalled();
  });

  it("processes every eligible message across multiple entries and messaging items", async () => {
    const deps = dependencies();
    vi.mocked(deps.persistence.insertOrGetMessage).mockImplementation(async (_followerId, inbound) => `uuid-${inbound.mid}`);
    const multi = { object: "instagram", entry: [
      { messaging: [
        { recipient: { id: "creator-ig-id" }, sender: { id: "follower-1" }, message: { mid: "mid-1" } },
        { recipient: { id: "creator-ig-id" }, sender: { id: "follower-2" }, message: { mid: "mid-2" } },
      ] },
      { messaging: [
        { recipient: { id: "creator-ig-id" }, sender: { id: "follower-3" }, message: { mid: "mid-3" } },
        { recipient: { id: "creator-ig-id" }, sender: { id: "follower-4" }, message: { mid: "echo-mid", is_echo: true } },
      ] },
    ] };
    expect(await processWebhook(request(multi), deps)).toEqual({ statusCode: 200 });
    expect(deps.persistence.insertOrGetMessage).toHaveBeenCalledTimes(3);
    expect(vi.mocked(deps.queue.send).mock.calls.map(([job]) => job.id))
      .toEqual(["triage:uuid-mid-1", "triage:uuid-mid-2", "triage:uuid-mid-3"]);
  });

  it("does not send to SQS when persistence fails", async () => {
    const deps = dependencies();
    vi.mocked(deps.persistence.insertOrGetMessage).mockRejectedValue(new Error("database unavailable"));
    await expect(processWebhook(request(), deps)).rejects.toThrow("database unavailable");
    expect(deps.queue.send).not.toHaveBeenCalled();
  });

  it("fails on SQS error, then reuses the same message UUID on webhook retry", async () => {
    const deps = dependencies();
    vi.mocked(deps.queue.send).mockRejectedValueOnce(new Error("queue unavailable"));
    await expect(processWebhook(request(), deps)).rejects.toThrow("queue unavailable");
    expect(await processWebhook(request(), deps)).toEqual({ statusCode: 200 });
    expect(deps.persistence.insertOrGetMessage).toHaveBeenCalledTimes(2);
    expect(deps.queue.send).toHaveBeenCalledTimes(2);
    expect(vi.mocked(deps.queue.send).mock.calls[0][0].payload.messageId).toBe("message-uuid");
    expect(vi.mocked(deps.queue.send).mock.calls[1][0].payload.messageId).toBe("message-uuid");
    expect(vi.mocked(deps.queue.send).mock.calls[0][0].id).toBe("triage:message-uuid");
    expect(vi.mocked(deps.queue.send).mock.calls[1][0].id).toBe("triage:message-uuid");
  });
});
