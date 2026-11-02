import "server-only";
import { createClient } from "@/lib/supabase/server";

// The one place that calls the staging POST /api/send Lambda (BASELINE.md 2.3: every write goes through it).
// It sends only the creator's session token, never the service-role key. It never logs the body:
// it holds DM, answer and tag text.

export const SESSION_EXPIRED = "Your session expired. Sign in again before sending.";

export type SendApiResult =
  /** Nothing was sent: no signed-in user, no session token, or no HTTPS API URL. */
  | { kind: "not_sent" }
  | { kind: "network_error" }
  | { kind: "timeout" }
  | {
      kind: "response";
      httpStatus: number;
      ok: boolean;
      /** `status` from the response body (`sent`, `pending`, `failed`), when it had one. */
      deliveryStatus: string | null;
      /** `error` code from the response body, when it had one. Never shown to the creator as is. */
      error: string | null;
    };

const TIMEOUT_MS = 25_000;

export async function postToSendApi(body: Record<string, unknown>): Promise<SendApiResult> {
  const supabase = await createClient();
  const { data: userData, error: userError } = await supabase.auth.getUser();
  if (userError || !userData.user) {
    return { kind: "not_sent" };
  }
  const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
  const jwt = sessionData.session?.access_token;
  const sendUrl = process.env.INSTAGRAM_SEND_API_URL;
  if (sessionError || !jwt || !sendUrl || !sendUrl.startsWith("https://")) {
    return { kind: "not_sent" };
  }

  let response: Response;
  try {
    response = await fetch(sendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${jwt}` },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    return error instanceof Error && error.name === "TimeoutError" ? { kind: "timeout" } : { kind: "network_error" };
  }

  let payload: { status?: unknown; error?: unknown } | null = null;
  try {
    payload = (await response.json()) as { status?: unknown; error?: unknown } | null;
  } catch {
    payload = null;
  }
  return {
    kind: "response",
    httpStatus: response.status,
    ok: response.ok,
    deliveryStatus: typeof payload?.status === "string" ? payload.status : null,
    error: typeof payload?.error === "string" ? payload.error : null,
  };
}
