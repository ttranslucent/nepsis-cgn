import { readNepsisUserFromRequest } from "@/lib/nepsisAuth";
import { envFlag, publicSiteMode } from "@/lib/publicMode";

const DEFAULT_ENGINE_BASE_URL = "http://127.0.0.1:8787";
const ENGINE_SESSION_OWNER_HEADER = "X-Nepsis-Session-Owner";

class EngineConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EngineConfigurationError";
  }
}

export function isEngineConfigurationError(error: unknown): error is EngineConfigurationError {
  return error instanceof EngineConfigurationError;
}

export function engineBaseUrl(): string {
  const configured = process.env.NEPSIS_API_BASE_URL?.trim();
  if (configured && configured.length > 0) {
    return configured;
  }
  if (process.env.NODE_ENV !== "production" && !publicSiteMode()) {
    return DEFAULT_ENGINE_BASE_URL;
  }
  throw new EngineConfigurationError(
    "NEPSIS_API_BASE_URL is not configured for this deployment.",
  );
}

function configuredEngineToken(): string | null {
  const token = process.env.NEPSIS_API_TOKEN?.trim();
  return token && token.length > 0 ? token : null;
}

export function anonymousEngineControlsAllowed(): boolean {
  return !publicSiteMode() && envFlag("NEPSIS_ENGINE_ALLOW_ANON");
}

export function engineControlOwner(request: Request): string | null {
  return readNepsisUserFromRequest(request);
}

function withEngineAuthHeaders(input?: HeadersInit, owner?: string | null): Headers {
  const headers = new Headers(input);
  const token = configuredEngineToken();
  if (token && !headers.has("Authorization") && !headers.has("X-API-Key")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (owner && !headers.has(ENGINE_SESSION_OWNER_HEADER)) {
    headers.set(ENGINE_SESSION_OWNER_HEADER, owner);
  }
  return headers;
}

export function requireEngineControlAuth(request: Request): Response | null {
  if (anonymousEngineControlsAllowed() || engineControlOwner(request)) {
    return null;
  }
  return Response.json(
    {
      error: "Unauthorized",
      detail: "Sign in required for engine session controls",
    },
    { status: 401 },
  );
}

export async function proxyEngineRequest(
  path: string,
  init?: RequestInit,
  options?: { owner?: string | null },
): Promise<Response> {
  const base = engineBaseUrl().replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const target = `${base}${normalizedPath}`;
  const headers = withEngineAuthHeaders(init?.headers, options?.owner);
  return fetch(target, { ...init, headers });
}

export function engineErrorResponse(error: unknown): Response {
  if (isEngineConfigurationError(error)) {
    return Response.json(
      {
        error: error.message,
        detail:
          "Set NEPSIS_API_BASE_URL to the public base URL of the Nepsis API before deploying this web app.",
      },
      { status: 503 },
    );
  }

  return Response.json(
    {
      error: "Engine backend request failed",
      detail: (error as Error)?.message ?? "Unknown error",
    },
    { status: 502 },
  );
}

export async function proxyJsonResponse(res: Response): Promise<Response> {
  const contentType = res.headers.get("content-type") ?? "";
  const text = await res.text();
  if (contentType.includes("application/json")) {
    return new Response(text, {
      status: res.status,
      headers: { "Content-Type": contentType },
    });
  }

  return new Response(
    JSON.stringify({
      error: "Upstream did not return JSON",
      detail: text,
    }),
    {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    },
  );
}
