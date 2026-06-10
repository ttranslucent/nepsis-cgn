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
      return buildBundledMvpFallbackResponse(body, "upstream_non_ok");
    }
    return proxyJsonResponse(upstream);
  } catch (error) {
    if (isEngineConfigurationError(error)) {
      return buildBundledMvpFallbackResponse(body, "backend_unconfigured");
    }
    if (publicSiteMode()) {
      return buildBundledMvpFallbackResponse(body, "public_fallback_after_proxy_error");
    }
    return engineErrorResponse(error);
  }
}
