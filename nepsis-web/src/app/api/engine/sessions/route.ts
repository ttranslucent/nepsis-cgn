import { proxyEngineRequest, proxyJsonResponse, requireEngineControlAuth } from "@/lib/engineApi";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const url = new URL(req.url);
  const suffix = url.search ? `/v1/sessions${url.search}` : "/v1/sessions";
  try {
    const upstream = await proxyEngineRequest(suffix, { method: "GET" });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return Response.json(
      {
        error: "Engine backend request failed",
        detail: (error as Error)?.message ?? "Unknown error",
      },
      { status: 502 },
    );
  }
}

export async function POST(req: Request) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const body = await req.text();
  try {
    const upstream = await proxyEngineRequest("/v1/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return Response.json(
      {
        error: "Engine backend request failed",
        detail: (error as Error)?.message ?? "Unknown error",
      },
      { status: 502 },
    );
  }
}

export async function DELETE(req: Request) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const url = new URL(req.url);
  const suffix = url.search ? `/v1/sessions${url.search}` : "/v1/sessions";
  try {
    const upstream = await proxyEngineRequest(suffix, { method: "DELETE" });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return Response.json(
      {
        error: "Engine backend request failed",
        detail: (error as Error)?.message ?? "Unknown error",
      },
      { status: 502 },
    );
  }
}
