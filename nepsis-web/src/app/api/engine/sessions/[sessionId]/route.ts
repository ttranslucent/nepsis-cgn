import {
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
  const { sessionId } = await params;
  try {
    const upstream = await proxyEngineRequest(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
      method: "GET",
    });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}

export async function DELETE(req: Request, { params }: RouteParams) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const { sessionId } = await params;
  try {
    const upstream = await proxyEngineRequest(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
