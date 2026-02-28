import { proxyEngineRequest, proxyJsonResponse } from "@/lib/engineApi";

export const runtime = "nodejs";

export async function GET() {
  try {
    const upstream = await proxyEngineRequest("/v1/routes", { method: "GET" });
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
