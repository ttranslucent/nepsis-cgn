import {
  engineControlOwner,
  engineErrorResponse,
  proxyEngineRequest,
  proxyJsonResponse,
  requireEngineControlAuth,
} from "@/lib/engineApi";

export const runtime = "nodejs";

type RouteParams = { params: Promise<{ sessionId: string }> };

export async function GET(req: Request, { params }: RouteParams) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const owner = engineControlOwner(req);
  const { sessionId } = await params;
  try {
    const upstream = await proxyEngineRequest(
      `/v1/sessions/${encodeURIComponent(sessionId)}/audit-export`,
      { method: "GET" },
      { owner },
    );
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
