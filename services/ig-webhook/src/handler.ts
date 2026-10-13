import { randomUUID } from "node:crypto";
import type { APIGatewayProxyEventV2, APIGatewayProxyStructuredResultV2 } from "aws-lambda";
import { parseInboundEvents, verifyMetaSignature } from "./meta";
import { createPersistence, createServiceRoleClient, type Persistence } from "./persistence";
import { createTriageQueue, type TriageJob, type TriageQueue } from "./queue";
import { loadConfig } from "./config";

export interface Dependencies { persistence: Persistence; queue: TriageQueue; appSecret: string }

export async function processWebhook(event: APIGatewayProxyEventV2, deps: Dependencies): Promise<APIGatewayProxyStructuredResultV2> {
  const rawBody = event.isBase64Encoded
    ? Buffer.from(event.body ?? "", "base64") : Buffer.from(event.body ?? "", "utf8");
  const signature = Object.entries(event.headers).find(([name]) => name.toLowerCase() === "x-hub-signature-256")?.[1];
  if (!verifyMetaSignature(rawBody, signature, deps.appSecret)) return { statusCode: 401 };

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawBody.toString("utf8"));
  } catch {
    return { statusCode: 400 };
  }

  const inboundEvents = parseInboundEvents(parsed);
  for (const inbound of inboundEvents) {
    const creatorId = await deps.persistence.resolveCreator(inbound.recipientIgUserId);
    if (!creatorId) throw new Error("Instagram account is not connected");
    const followerId = await deps.persistence.upsertFollower(creatorId, inbound);
    const messageId = await deps.persistence.insertOrGetMessage(followerId, inbound);
    const job: TriageJob = {
      v: 1,
      type: "triage",
      id: `triage:${messageId}`,
      creatorId,
      traceId: randomUUID(),
      createdAt: new Date().toISOString(),
      payload: { messageId },
    };
    // A retry may send a second SQS message, but this stable job ID lets the consumer
    // recognize both deliveries as the same triage operation. No outbox exists yet.
    await deps.queue.send(job);
  }
  return { statusCode: 200 };
}

export async function handler(event: APIGatewayProxyEventV2): Promise<APIGatewayProxyStructuredResultV2> {
  try {
    const config = await loadConfig();
    return await processWebhook(event, {
      appSecret: config.metaAppSecret,
      persistence: createPersistence(createServiceRoleClient(config.supabaseUrl, config.supabaseServiceRoleKey)),
      queue: createTriageQueue(),
    });
  } catch (error) {
    // Do not log event bodies, DM text, or secrets. A non-2xx response asks Meta to retry.
    console.error("Instagram webhook processing failed", { name: error instanceof Error ? error.name : "Unknown" });
    return { statusCode: 500 };
  }
}
