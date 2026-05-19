import { engineErrorResponse, isEngineConfigurationError, proxyEngineRequest, proxyJsonResponse } from "@/lib/engineApi";
import { buildBundledMvpFallbackResponse } from "@/lib/mvpFallback";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const body = await req.text();
  try {
    const upstream = await proxyEngineRequest("/v1/mvp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    return proxyJsonResponse(upstream);
  } catch (error) {
    if (isEngineConfigurationError(error)) {
      return buildBundledMvpFallbackResponse(body);
    }
    return engineErrorResponse(error);
  }
}
