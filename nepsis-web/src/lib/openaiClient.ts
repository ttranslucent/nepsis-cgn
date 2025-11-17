const DEFAULT_MODEL = process.env.OPENAI_MODEL ?? "gpt-4.1-mini";
const API_URL = process.env.OPENAI_API_URL ?? "https://api.openai.com/v1/responses";
const API_KEY = process.env.OPENAI_API_KEY ?? process.env.NEPSIS_OPENAI_API_KEY ?? "";

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
        model: args.model ?? DEFAULT_MODEL,
        input: args.input,
      };
      return this.request(payload);
    },
  };
}

export const openai = new SimpleOpenAiClient(API_KEY, API_URL);
