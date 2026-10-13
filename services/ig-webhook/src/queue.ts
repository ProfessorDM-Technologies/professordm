import { SQSClient, SendMessageCommand } from "@aws-sdk/client-sqs";
import type { JobEnvelope } from "@professordm/contracts";

export type TriageJob = JobEnvelope<"triage", { messageId: string }>;
export interface TriageQueue { send(job: TriageJob): Promise<void> }

export function createTriageQueue(): TriageQueue {
  const queueUrl = process.env.AI_JOBS_QUEUE_URL;
  if (!queueUrl) throw new Error("AI jobs queue configuration is missing");
  const client = new SQSClient({});
  return {
    async send(job) {
      await client.send(new SendMessageCommand({ QueueUrl: queueUrl, MessageBody: JSON.stringify(job) }));
    },
  };
}
