import { GetParameterCommand, type SSMClient } from "@aws-sdk/client-ssm";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadConfig, resetConfigCache } from "./config";

const variableNames = [
  "META_APP_SECRET_PARAMETER",
  "SUPABASE_SERVICE_ROLE_KEY_PARAMETER",
  "SUPABASE_URL_PARAMETER",
] as const;
const originalEnvironment = Object.fromEntries(variableNames.map((name) => [name, process.env[name]]));
const names = {
  META_APP_SECRET_PARAMETER: "/professordm/staging/meta-app-secret",
  SUPABASE_SERVICE_ROLE_KEY_PARAMETER: "/professordm/staging/supabase-service-role-key",
  SUPABASE_URL_PARAMETER: "/professordm/staging/supabase-url",
};
const values = new Map([
  [names.META_APP_SECRET_PARAMETER, "synthetic-meta-value"],
  [names.SUPABASE_SERVICE_ROLE_KEY_PARAMETER, "synthetic-service-role-value"],
  [names.SUPABASE_URL_PARAMETER, "https://synthetic.example.invalid"],
]);

function client() {
  const send = vi.fn(async (command: GetParameterCommand): Promise<{ Parameter: { Value?: string } }> => ({
    Parameter: { Value: values.get(command.input.Name ?? "") },
  }));
  return { send, ssm: { send } as unknown as SSMClient };
}

beforeEach(() => {
  Object.assign(process.env, names);
  resetConfigCache();
});

afterEach(() => {
  for (const name of variableNames) {
    const original = originalEnvironment[name];
    if (original === undefined) delete process.env[name];
    else process.env[name] = original;
  }
  resetConfigCache();
  vi.restoreAllMocks();
});

describe("runtime SSM configuration", () => {
  it("loads all three parameters and decrypts only the SecureStrings", async () => {
    const { send, ssm } = client();
    expect(await loadConfig(ssm)).toEqual({
      metaAppSecret: "synthetic-meta-value",
      supabaseServiceRoleKey: "synthetic-service-role-value",
      supabaseUrl: "https://synthetic.example.invalid",
    });
    expect(send.mock.calls.map(([command]) => command.input)).toEqual([
      { Name: names.META_APP_SECRET_PARAMETER, WithDecryption: true },
      { Name: names.SUPABASE_SERVICE_ROLE_KEY_PARAMETER, WithDecryption: true },
      { Name: names.SUPABASE_URL_PARAMETER, WithDecryption: false },
    ]);
  });

  it("fails before calling SSM if a parameter-name environment variable is missing", () => {
    const { send, ssm } = client();
    delete process.env.SUPABASE_URL_PARAMETER;
    expect(() => loadConfig(ssm)).toThrow("Missing SUPABASE_URL_PARAMETER configuration");
    expect(send).not.toHaveBeenCalled();
  });

  it("fails safely when SSM returns no value", async () => {
    const { send, ssm } = client();
    send.mockResolvedValueOnce({ Parameter: {} });
    await expect(loadConfig(ssm)).rejects.toThrow("SSM returned no value for META_APP_SECRET_PARAMETER");
  });

  it("hides SSM errors and retries after a failed load", async () => {
    const { send, ssm } = client();
    send.mockRejectedValueOnce(new Error("synthetic internal detail"));
    await expect(loadConfig(ssm)).rejects.toThrow("Could not load META_APP_SECRET_PARAMETER from SSM");
    expect(await loadConfig(ssm)).toHaveProperty("metaAppSecret", "synthetic-meta-value");
    expect(send).toHaveBeenCalledTimes(6);
  });

  it("caches a successful load across warm and concurrent calls", async () => {
    const { send, ssm } = client();
    const [first, concurrent] = await Promise.all([loadConfig(ssm), loadConfig(ssm)]);
    expect(first).toBe(concurrent);
    expect(await loadConfig(ssm)).toBe(first);
    expect(send).toHaveBeenCalledTimes(3);
  });

  it("never logs returned parameter values", async () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { ssm } = client();
    await loadConfig(ssm);
    expect(log).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
  });
});
