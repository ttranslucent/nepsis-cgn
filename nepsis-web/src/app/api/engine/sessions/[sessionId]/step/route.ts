import {
  engineControlOwner,
  engineErrorResponse,
  proxyEngineRequest,
  proxyJsonResponse,
  requireEngineControlAuth,
} from "@/lib/engineApi";
import { requireCsrfToken } from "@/lib/requestSecurity";

export const runtime = "nodejs";

type RouteParams = { params: Promise<{ sessionId: string }> };

export async function POST(req: Request, { params }: RouteParams) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const csrfFailure = requireCsrfToken(req);
  if (csrfFailure) {
    return csrfFailure;
  }
  const owner = engineControlOwner(req);
  const { sessionId } = await params;
  const body = await req.text();
  try {
    const upstream = await proxyEngineRequest(`/v1/sessions/${encodeURIComponent(sessionId)}/step`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    }, { owner });
    return proxyJsonResponse(upstream);
  } catch (error) {
    return engineErrorResponse(error);
  }
}
