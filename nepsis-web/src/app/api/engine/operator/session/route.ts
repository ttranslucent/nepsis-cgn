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
  try {
    const upstream = await proxyEngineRequest("/v1/operator/session", { method: "GET" }, { owner });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
