export const DEFAULT_OPENAI_MODEL = process.env.OPENAI_MODEL ?? "gpt-4.1-mini";
const API_URL = process.env.OPENAI_API_URL ?? "https://api.openai.com/v1/responses";

function normalizeApiKey(value?: string | null): string {
  return typeof value === "string" ? value.trim() : "";
}

function isPlaceholderOpenAiKey(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  return (
    normalized === "your_openai_api_key_here" ||
    normalized.startsWith("replace-with-") ||
    normalized.includes("server-side-openai-key")
  );
}

function configuredEnvApiKey(): string {
  for (const candidate of [process.env.OPENAI_API_KEY, process.env.NEPSIS_OPENAI_API_KEY]) {
    const normalized = normalizeApiKey(candidate);
    if (normalized && !isPlaceholderOpenAiKey(normalized)) {
      return normalized;
    }
  }
  return "";
}

const ENV_API_KEY = configuredEnvApiKey();

type CreateResponseArgs = {
  model?: string;
  input: string;
};

class SimpleOpenAiClient {
  private apiKey: string;
  private endpoint: string;

  constructor(apiKey: string, endpoint: string) {
    this.apiKey = apiKey;
    this.endpoint = endpoint;
  }

  private async request(body: Record<string, unknown>) {
    if (!this.apiKey) {
      throw new Error("OPENAI_API_KEY is not configured for this environment.");
    }

    const res = await fetch(this.endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
        "OpenAI-Beta": "responses-2024-12-01=v1",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`OpenAI request failed (${res.status}): ${detail}`);
    }

    return res.json();
  }

  public readonly responses = {
    create: (args: CreateResponseArgs) => {
      const payload = {
        model: args.model ?? DEFAULT_OPENAI_MODEL,
        input: args.input,
      };
      return this.request(payload);
    },
  };
}

export function createOpenAiClient(): SimpleOpenAiClient {
  return new SimpleOpenAiClient(ENV_API_KEY, API_URL);
}

export function hasConfiguredOpenAiKey(): boolean {
  return normalizeApiKey(ENV_API_KEY).length > 0;
}

export function extractOpenAiText(payload: Record<string, unknown> | null | undefined): string {
  if (!payload) {
    return "";
  }

  const outputText = payload.output_text;
  if (typeof outputText === "string") {
    return outputText;
  }
  if (Array.isArray(outputText)) {
    return outputText.filter((chunk): chunk is string => typeof chunk === "string").join("\n\n");
  }

  const output = payload.output;
  if (!Array.isArray(output)) {
    return "";
  }

  const chunks: string[] = [];
  for (const item of output) {
    if (typeof item !== "object" || item === null) {
      continue;
    }
    const content = (item as { content?: unknown }).content;
    if (!Array.isArray(content)) {
      continue;
    }
    for (const chunk of content) {
      if (typeof chunk !== "object" || chunk === null) {
        continue;
      }
      const text = (chunk as { text?: unknown }).text;
      if (typeof text === "string" && text.length > 0) {
        chunks.push(text);
      }
    }
  }

  return chunks.join("\n\n");
}

export const openai = createOpenAiClient();
