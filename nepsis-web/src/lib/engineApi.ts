const DEFAULT_ENGINE_BASE_URL = "http://127.0.0.1:8787";

export function engineBaseUrl(): string {
  const configured = process.env.NEPSIS_API_BASE_URL?.trim();
  return configured && configured.length > 0 ? configured : DEFAULT_ENGINE_BASE_URL;
}

function configuredEngineToken(): string | null {
  const token = process.env.NEPSIS_API_TOKEN?.trim();
  return token && token.length > 0 ? token : null;
}

function withEngineAuthHeaders(input?: HeadersInit): Headers {
  const headers = new Headers(input);
  const token = configuredEngineToken();
  if (token && !headers.has("Authorization") && !headers.has("X-API-Key")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

function hasNepsisUserCookie(request: Request): boolean {
  const cookieHeader = request.headers.get("cookie") ?? "";
  if (!cookieHeader) {
    return false;
  }
  return cookieHeader
    .split(";")
    .map((entry) => entry.trim())
    .some((entry) => entry.startsWith("nepsis_user=") && entry.length > "nepsis_user=".length);
}

export function requireEngineControlAuth(request: Request): Response | null {
  const allowAnonymous = process.env.NEPSIS_ENGINE_ALLOW_ANON === "true";
  if (allowAnonymous || hasNepsisUserCookie(request)) {
    return null;
  }
  return Response.json(
    {
      error: "Unauthorized",
      detail: "Sign in required for engine control routes",
    },
    { status: 401 },
  );
}

export async function proxyEngineRequest(path: string, init?: RequestInit): Promise<Response> {
  const base = engineBaseUrl().replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const target = `${base}${normalizedPath}`;
  const headers = withEngineAuthHeaders(init?.headers);
  return fetch(target, { ...init, headers });
}

export async function proxyJsonResponse(res: Response): Promise<Response> {
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const data = await res.json();
    return new Response(JSON.stringify(data), {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  }
  const text = await res.text();
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
