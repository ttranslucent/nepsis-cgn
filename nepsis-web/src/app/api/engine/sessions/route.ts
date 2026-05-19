import {
  engineControlOwner,
  engineErrorResponse,
  proxyEngineRequest,
  proxyJsonResponse,
  requireEngineControlAuth,
} from "@/lib/engineApi";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const owner = engineControlOwner(req);
  const url = new URL(req.url);
  const suffix = url.search ? `/v1/sessions${url.search}` : "/v1/sessions";
  try {
    const upstream = await proxyEngineRequest(suffix, { method: "GET" }, { owner });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}

export async function POST(req: Request) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const owner = engineControlOwner(req);
  const body = await req.text();
  try {
    const upstream = await proxyEngineRequest("/v1/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    }, { owner });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}

export async function DELETE(req: Request) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const owner = engineControlOwner(req);
  const url = new URL(req.url);
  const suffix = url.search ? `/v1/sessions${url.search}` : "/v1/sessions";
  try {
    const upstream = await proxyEngineRequest(suffix, { method: "DELETE" }, { owner });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
