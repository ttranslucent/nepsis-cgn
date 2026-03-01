import { proxyEngineRequest, proxyJsonResponse, requireEngineControlAuth } from "@/lib/engineApi";

export const runtime = "nodejs";

type RouteParams = { params: Promise<{ sessionId: string }> };

export async function POST(req: Request, { params }: RouteParams) {
  const unauthorized = requireEngineControlAuth(req);
  if (unauthorized) {
    return unauthorized;
  }
  const { sessionId } = await params;
  const body = await req.text();
  try {
    const upstream = await proxyEngineRequest(`/v1/sessions/${encodeURIComponent(sessionId)}/step`, {
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
