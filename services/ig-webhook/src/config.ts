import { GetParameterCommand, SSMClient } from "@aws-sdk/client-ssm";

export interface WebhookConfig {
  metaAppSecret: string;
  supabaseServiceRoleKey: string;
  supabaseUrl: string;
}

const ssm = new SSMClient({});
let cachedConfig: Promise<WebhookConfig> | undefined;

function parameterName(variable: string): string {
  const name = process.env[variable];
  if (!name) throw new Error(`Missing ${variable} configuration`);
  return name;
}

async function parameterValue(client: SSMClient, name: string, variable: string, decrypt: boolean): Promise<string> {
  let value: string | undefined;
  try {
    const response = await client.send(new GetParameterCommand({ Name: name, WithDecryption: decrypt }));
    value = response.Parameter?.Value;
  } catch {
    throw new Error(`Could not load ${variable} from SSM`);
  }
  if (!value) throw new Error(`SSM returned no value for ${variable}`);
  return value;
}

export function loadConfig(client: SSMClient = ssm): Promise<WebhookConfig> {
  if (cachedConfig) return cachedConfig;

  const metaName = parameterName("META_APP_SECRET_PARAMETER");
  const keyName = parameterName("SUPABASE_SERVICE_ROLE_KEY_PARAMETER");
  const urlName = parameterName("SUPABASE_URL_PARAMETER");

  cachedConfig = Promise.all([
    parameterValue(client, metaName, "META_APP_SECRET_PARAMETER", true),
    parameterValue(client, keyName, "SUPABASE_SERVICE_ROLE_KEY_PARAMETER", true),
    parameterValue(client, urlName, "SUPABASE_URL_PARAMETER", false),
  ]).then(([metaAppSecret, supabaseServiceRoleKey, supabaseUrl]) => ({
    metaAppSecret, supabaseServiceRoleKey, supabaseUrl,
  })).catch((error: unknown) => {
    cachedConfig = undefined;
    throw error;
  });
  return cachedConfig;
}

export function resetConfigCache(): void {
  cachedConfig = undefined;
}
