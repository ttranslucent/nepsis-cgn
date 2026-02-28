import { proxyEngineRequest, proxyJsonResponse, requireEngineControlAuth } from "@/lib/engineApi";

export const runtime = "nodejs";

type RouteParams = { params: { sessionId: string } };

export async function GET(req: Request, { params }: RouteParams) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const { sessionId } = params;
  const url = new URL(req.url);
  const suffix = url.search
    ? `/v1/sessions/${encodeURIComponent(sessionId)}/packets${url.search}`
    : `/v1/sessions/${encodeURIComponent(sessionId)}/packets`;
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
