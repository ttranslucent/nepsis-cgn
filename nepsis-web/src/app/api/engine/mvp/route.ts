import { engineErrorResponse, isEngineConfigurationError, proxyEngineRequest, proxyJsonResponse } from "@/lib/engineApi";
import { buildBundledMvpFallbackResponse } from "@/lib/mvpFallback";
import { publicSiteMode } from "@/lib/publicMode";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const body = await req.text();
  try {
    const upstream = await proxyEngineRequest("/v1/mvp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (publicSiteMode() && !upstream.ok) {
      return buildBundledMvpFallbackResponse(body);
    }
    return proxyJsonResponse(upstream);
  } catch (error) {
    if (isEngineConfigurationError(error) || publicSiteMode()) {
      return buildBundledMvpFallbackResponse(body);
    }
    return engineErrorResponse(error);
  }
}
