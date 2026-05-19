import { engineErrorResponse, isEngineConfigurationError, proxyEngineRequest, proxyJsonResponse } from "@/lib/engineApi";

export const runtime = "nodejs";

export async function GET() {
  try {
    const upstream = await proxyEngineRequest("/v1/health", { method: "GET" });
    return proxyJsonResponse(upstream);
  } catch (error) {
    if (isEngineConfigurationError(error)) {
      return Response.json({
        ok: false,
        configured: false,
        detail: "NEPSIS_API_BASE_URL is not configured for this deployment.",
      });
    }
    return engineErrorResponse(error);
  }
}
